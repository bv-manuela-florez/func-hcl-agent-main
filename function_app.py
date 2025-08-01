import azure.functions as func
import logging
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import ListSortOrder
from azure.identity import ClientSecretCredential
import os
import json
import time
import requests  # <-- Añade importación de requests
from cosmos_utils.chat_history_models import ConversationChat, ConversationChatInput, ConversationChatResponse, TokenUsage
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="agent_httptrigger")
def agent_httptrigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    message = req.params.get('message')
    agentid = req.params.get('agentid')
    threadid = req.params.get('threadid')

    if not message or not agentid:
        try:
            req_body = req.get_json()
        except ValueError:
            req_body = None

        if req_body:
            message = req_body.get('message')
            agentid = req_body.get('agentid')
            threadid = req_body.get('threadid')
    logging.info(f"Received message: {message}, agentid: {agentid}, threadid: {threadid}")
    if not message or not agentid:
        return func.HttpResponse(
            "Pass in a message and agentid in the query string or in the request body for a personalized response.",
            status_code=400
        )

    try:
        # Llama a la Azure Function que devuelve documentos
        search_endpoint = os.environ.get("FUCTION_ENDPOINT")
        search_params = {
            "q": message,
            "code": os.environ.get("FUNCTION_KEY")
        }
        logging.info(f"Calling search endpoint with params: {search_params}")
        try:
            search_response = requests.get(search_endpoint, params=search_params)
            search_response.raise_for_status()
            search_result = search_response.json()
            docs = search_result.get("semantic_documents", [])
            logging.info(f"Documentos obtenidos: {len(docs)}")
            context = "\n\n".join([
                f"Titulo de la tabla: {doc.get('metadata_spo_item_table_title')}\n"
                # f"Descripción:\n{doc.get('content_description', '')}\n\n"
                f"Enlace al documento: {doc.get('metadata_spo_item_path')}\n\n"
                f"Markdown:\n{doc.get('markdown_content', '')}\n\n"
                f"Fecha del reporte: {doc.get('metadata_spo_item_release_date')}\n\n"
                # f"Embedding:\n{json.dumps(doc.get('embedding', [])) if doc.get('embedding') else ''}"
                for doc in docs
            ])
            logging.info(f"Contexto obtenido: {context}")
            message_with_context = f"Pregunta:\n{message}\n\nContexto:\n{context}"
        except Exception as e:
            logging.error(f"Error al obtener documentos: {str(e)}")
            message_with_context = message

        # Initialize the AIProjectClient with the endpoint
        # pip install azure-ai-projects==1.0.0b11
        project_client = AIProjectClient(
            credential=ClientSecretCredential(
                    tenant_id=os.environ["AZURE_TENANT_ID"],
                    client_id=os.environ["AZURE_CLIENT_ID"],
                    client_secret=os.environ["AZURE_CLIENT_SECRET"]
                    ),
            endpoint=os.environ.get("AI_PROJECT_ENDPOINT")
        )

        agent = project_client.agents.get_agent(agentid)
        if not agent:
            logging.error(f"Agent with ID {agentid} not found.")
            return func.HttpResponse(
                f"Agent with ID {agentid} not found.",
                status_code=404
            )

        if not threadid:
            logging.info("Creating a new thread for the agent.")
            thread_response = project_client.agents.threads.create()
            thread_id = thread_response.id
        else:
            logging.info(f"Using existing thread ID: {threadid}")
            thread_id = threadid

        message_obj = project_client.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=message_with_context
        )

        run = project_client.agents.runs.create(
            thread_id=thread_id,
            agent_id=agent.id
        )
        while run.status not in ("completed", "failed"):
            time.sleep(1)
            run = project_client.agents.runs.get(thread_id=thread_id, run_id=run.id)

        token_usage_data = run.usage
        messages = list(project_client.agents.messages.list(thread_id=thread_id))
        assistant_text = "No assistant message found."
        for msg in messages:
            if msg.role == "assistant":
                if msg.content and isinstance(msg.content, list):
                    for part in msg.content:
                        if part.get("type") == "text" and "text" in part and "value" in part["text"]:
                            raw_text = part["text"]["value"]
                            logging.info("Respuesta del agente: %s", part["text"]["value"])
                            assistant_text = raw_text
                            break
                break

        # Save chat history to Cosmos DB
        try:
            # Create ConversationChatInput for user message
            user_input = ConversationChatInput(
                message=message_with_context,
                user_id=None,  # As per comment in model
                user=None,     # As per comment in model
                attachments=None  # As per comment in model
            )

            # Create ConversationChatResponse for agent response
            agent_response = ConversationChatResponse(
                task_id=thread_id,  # Using thread_id as task_id as per comment
                task_status='InProgress',   # As per comment in model
                context_id=None,    # As per comment in model
                content=assistant_text,
                citations=None,     # As per comment in model
                safety_alert=None   # As per comment in model
            )

            # Convert token usage data to our custom model
            custom_token_usage = None
            if token_usage_data:
                custom_token_usage = TokenUsage(
                    total_tokens=getattr(token_usage_data, 'total_tokens', None),
                    prompt_tokens=getattr(token_usage_data, 'prompt_tokens', None),
                    completion_tokens=getattr(token_usage_data, 'completion_tokens', None)
                )

            # Create ConversationChat to save the full conversation
            conversation = ConversationChat(
                session_id=thread_id,  # Using thread_id as session_id
                user_id=None,          # As per comment in model
                token_usage=custom_token_usage,      # Could be populated if token usage info is available
                feedback=None,         # As per comment in model
                request=user_input,
                response=agent_response,
                updated=None          # As per comment in model
            )

            # Save to Cosmos DB
            saved_conversation = conversation.save()
            logging.info(f"Chat history saved successfully with ID: {saved_conversation.id}")

        except Exception as e:
            logging.error(f"Error saving chat history: {str(e)}")
            # Continue execution even if saving fails
        response_data = {
            "message": assistant_text,
            "threadId": thread_id
        }
        return func.HttpResponse(
            json.dumps(response_data),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        # Include more detailed error information for debugging
        import traceback
        logging.error(traceback.format_exc())
        return func.HttpResponse(
            "Internal Server Error: " + str(e),
            status_code=500
        )
# Reduce el nivel de logging de Azure y requests para evitar ruido en consola


logging.getLogger('azure').setLevel(logging.WARNING)
logging.getLogger(
    'azure.core.pipeline.policies.http_logging_policy'
).setLevel(logging.WARNING)
logging.getLogger('azure.storage').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
