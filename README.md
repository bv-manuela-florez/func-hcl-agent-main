# foundry-agent-endpoint

## Overview

The `foundry-agent-endpoint` is a Python-based Azure Function application designed to serve as an endpoint for an agent hosted in Azure AI Foundry.
It interacts with Azure AI Projects and external Azure Functions for document retrieval and context enrichment.

This application:
1. Receives user requests with a message and agent ID.
2. Calls an external Azure Function to retrieve relevant documents based on the user's message.
3. Passes the retrieved documents as context, along with the user's question, to an Azure AI agent hosted in Azure AI Foundry.
4. Returns the agent's response to the user, maintaining thread continuity.

## Features

- **HTTP Trigger**: Provides an anonymous endpoint `/agent_httptrigger` to accept user inputs.
- **Document Enrichment**: Integrates with an external Azure Function to fetch semantic documents for context.
- **Azure AI Agent Integration**: Uses the `azure-ai-projects` library to interact with agents, threads, and messages.
- **Thread Management**: Supports thread continuity for multi-turn conversations.
- **Error Handling**: Robust error checking and logging.

## Prerequisites

- Azure Functions Core Tools
- Python 3.8 or later
- Required libraries in `requirements.txt`
- Azure Subscription for AI Projects and Azure Functions

## Installation

1. Clone the repository:
    ```bash
    git clone https://github.com/azure-data-ai-hub/azure-ai-foundry-agent.git
    cd azure-ai-foundry-agent
    ```

2. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3. Set up environment variables:
    - `AIProjectEndpoint`
    - `AZURE_TENANT_ID`
    - `AZURE_CLIENT_ID`
    - `AZURE_CLIENT_SECRET`
    - `FUCTION_ENDPOINT` (URL of the external Azure Function for document retrieval)
    - `FUNCTION_KEY` (if required by the external function)

4. Run the Azure Function locally:
    ```bash
    func start
    ```

## How It Works

1. **User Request**: The user sends a message, agent ID, and optionally a thread ID to the `/agent_httptrigger` endpoint.
2. **Document Retrieval**: The function calls an external Azure Function, passing the user's message to retrieve relevant semantic documents.
3. **Context Construction**: The retrieved documents are formatted and combined with the user's question to build a rich context.
4. **Agent Processing**: The context and question are sent to the specified Azure AI agent, which processes and generates a response.
5. **Response**: The agent's answer is returned to the user, along with the thread ID for continuity.

## HTTP Trigger Details

### Endpoint

`POST /agent_httptrigger`

### Query Parameters / Request Body

| Name       | Type   | Description                          |
|------------|--------|--------------------------------------|
| `message`  | string | The user message/question.           |
| `agentid`  | string | The ID of the AI agent.              |
| `threadid` | string | (Optional) The thread ID for context.|

### Request Example

```json
{
  "message": "¿Cual es la producción diaria gross desarrollo de la hocha del 12 de abril?",
  "agentid": "agent123",
  "threadid": "thread456"
}
```

### Response Example

```json
{
  "message": "La producción diaria gross desarrollo de la Hocha el 12 de abril de 2025 fue de 700 BOE. \n\nPuedes encontrar más detalles en el documento disponible [aquí](https://ecopetrol.sharepoint.com/sites/HOCOL-HOCOLBOT/Documentos%20compartidos/RP/RepDia_20250412(email).pdf)",
  "threadId": "thread456"
}
```

## Notes


- The agent always receives the user's question and the document context (if available).
- Thread IDs are used to maintain conversation state across requests.

