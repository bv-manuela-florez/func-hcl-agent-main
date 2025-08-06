import azure.functions as func
import logging
import os
import json
import asyncio
import requests
import traceback
from cosmos_utils.chat_history_models import ConversationChat, ConversationChatInput, ConversationChatResponse, Fingerprint, TokenUsage, Agent, datetime_factory
from agent_services.agent import AgentService
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="agent_httptrigger")
def agent_httptrigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    message = req.params.get('message')
    agent_id = req.params.get('agent_id')
    thread_id = req.params.get('thread_id')

    if not message or not agent_id:
        try:
            req_body = req.get_json()
        except ValueError:
            req_body = None

        if req_body:
            message = req_body.get('message')
            agent_id = req_body.get('agent_id')
            thread_id = req_body.get('thread_id')
    logging.info(f"Received message: {message}, agent_id: {agent_id}, thread_id: {thread_id}")
    if not message or not agent_id:
        return func.HttpResponse(
            "Pass in a message and agent_id in the query string or in the request body for a personalized response.",
            status_code=400
        )

    try:
        # Get context from search endpoint
        context = ""
        search_endpoint = os.environ.get("FUCTION_ENDPOINT")
        if search_endpoint:
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
                    f"Enlace al documento: {doc.get('metadata_spo_item_path')}\n\n"
                    f"Markdown:\n{doc.get('markdown_content', '')}\n\n"
                    f"Fecha del reporte: {doc.get('metadata_spo_item_release_date')}\n\n"
                    for doc in docs
                ])
                logging.info(f"Contexto obtenido: {context}")
            except Exception as e:
                logging.error(f"Error al obtener documentos: {str(e)}")
                context = ""

        # Prepare message with context
        message_with_context = message

        # Run the async function call
        result = asyncio.run(function_call_async(message_with_context, agent_id, thread_id, context))
        
        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        # Include more detailed error information for debugging
        logging.error(traceback.format_exc())
        return func.HttpResponse(
            "Internal Server Error: " + str(e),
            status_code=500
        )

async def function_call_async(message: str, agent_id: str, thread_id: str = None, context: str = "") -> dict:
    """
    Async function to handle agent invocation and chat history saving.
    Based on the provided function_call logic.
    """
    try:
        # Construct the chat input
        chat_input = ConversationChatInput(
            channel='Teams',
            user_id=None,  # As per comment in model
            message=message,
            context=context,
            attachments=None,  # As per comment in model
            datetime=datetime_factory(),
        )

        # Instantiate a new AgentService and invoke the agent
        agent_service = AgentService(thread_id=thread_id, agent_id=agent_id)
        agent_response, agent_token_usage, session_id = await agent_service.invoke(message)
        
        if not agent_response:
            raise ValueError("Agent response is empty")

        # Create a new ConversationChat instance
        conversation = ConversationChat(
            session_id=session_id,
            user_id=None,  # As per comment in model
            request=chat_input,
            response=agent_response,
            token_usage=agent_token_usage
        )
        
        assert conversation.response is not None, "Agent response cannot be None"

        # Prepare the response data
        response_data = {
            "message": conversation.response.content,
            "thread_id": session_id,
            "agent_id": conversation.response.agent_id
        }

        # Save the message in the background after response is created
        async def save_message_background():
            try:
                update = Fingerprint(
                    user_id=None,  # As per comment in model
                    datetime=datetime_factory()
                )
                conversation.updated = update
                saved_conversation = conversation.save()
                logging.info(f"✅ Chat history saved successfully with ID: {saved_conversation.id}")
            except Exception as e:
                logging.error(f"❌ Error saving chat history to database: {e}")

        # Start the save operation in the background
        asyncio.create_task(save_message_background())

        # Close the agent service
        await agent_service.close()

        return response_data

    except Exception as e:
        logging.error(f"Error in function_call_async: {e}")
        raise Exception(f"Error submit call function: {e}")

# Reduce el nivel de logging de Azure y requests para evitar ruido en consola


logging.getLogger('azure').setLevel(logging.WARNING)
logging.getLogger(
    'azure.core.pipeline.policies.http_logging_policy'
).setLevel(logging.WARNING)
logging.getLogger('azure.storage').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
