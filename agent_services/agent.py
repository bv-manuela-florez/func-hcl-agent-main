import logging
import os
from tenacity import AsyncRetrying, retry_if_exception_type, wait_exponential, stop_after_attempt
from cosmos_utils.chat_history_models import (
    Citation,
    CitationRangeFile,
    ConversationChatResponse,
    MessageRole,
    TokenUsage,
    datetime_factory,
)
from azure.core.exceptions import HttpResponseError
from azure.identity import ClientSecretCredential
from azure.ai.projects.aio import AIProjectClient


class RateLimitException(Exception):
    pass


class AgentService:
    """
    Class to handle agent services.
    This class is used to handle invokes of agents and other related services.
    """

    _thread = None
    _agent_client = None
    _project_client = None
    _agent_id = None

    def __init__(self, thread_id: str | None = None, agent_id: str | None = None):
        self._agent_id = agent_id
        self._thread_id = thread_id

        if not self._agent_id:
            raise ValueError("Agent ID is not set")

    async def _initialize_client(self):
        """Initialize the async agent client."""
        if not self._project_client:
            try:
                credentials = ClientSecretCredential(
                    tenant_id=os.environ["AZURE_TENANT_ID"],
                    client_id=os.environ["AZURE_CLIENT_ID"],
                    client_secret=os.environ["AZURE_CLIENT_SECRET"]
                )
                self._project_client = AIProjectClient(
                    credential=credentials,
                    endpoint=os.environ.get("AI_PROJECT_ENDPOINT")
                )

                # Get the agent to verify it exists
                agent = await self._project_client.agents.get_agent(self._agent_id)
                if not agent:
                    logging.error(f"Agent with ID {self._agent_id} not found.")
                    raise ValueError(f"Agent with ID {self._agent_id} not found.")

                self._agent_client = self._project_client.agents
                logging.debug("Agent client initialized successfully")
            except Exception as e:
                logging.error(f"Error creating agent client: {e}")
                raise e

    async def _retryable_call_to_foundry(self, agent_id: str = None):
        """
        Retryable function that retrieves the last message from the agent.
        """
        if agent_id is None:
            agent_id = self._agent_id
        if not self._agent_client:
            raise ValueError("Agent client is not initialized")
        if not self._thread:
            raise ValueError("Thread is not initialized")

        retries = 0
        token_usage = TokenUsage(
            agent_id=agent_id,
            total_tokens=0,
            prompt_tokens=0,
            completion_tokens=0
        )

        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type((RateLimitException, HttpResponseError, ValueError)),
            wait=wait_exponential(multiplier=1, min=6, max=10),
            stop=stop_after_attempt(10)
        ):
            with attempt:
                retries = attempt.retry_state.attempt_number - 1
                try:
                    agent_run = await self._agent_client.runs.create_and_process(
                        thread_id=self._thread.id,
                        agent_id=agent_id
                    )
                except HttpResponseError as e:
                    logging.error(f"Error creating agent run for thread {self._thread.id}: {e}")
                    raise e

                token_usage.total_tokens += agent_run.usage.total_tokens
                token_usage.prompt_tokens += agent_run.usage.prompt_tokens
                token_usage.completion_tokens += agent_run.usage.completion_tokens

                try:
                    message_res = await self._agent_client.messages.get_last_message_by_role(
                        thread_id=self._thread.id,
                        role=MessageRole.AGENT
                    )

                    if not message_res or message_res.status == "failed":
                        logging.warning(f"No response from agent or message failed for thread {self._thread.id}")
                        raise RateLimitException("Rate limit reached or message failed, retrying...")
                    if message_res.agent_id != agent_id:
                        logging.warning(
                            f"Agent mismatch. {self._thread.id}: expected {agent_id}, "
                            f"got {message_res.agent_id}"
                        )
                        raise ValueError(f"Agent ID mismatch: expected {agent_id}, got {message_res.agent_id}")

                    # Success - return the result
                    return token_usage, message_res, retries
                except HttpResponseError as e:
                    if hasattr(e, 'status_code') and e.status_code == 429:  # Rate limit error
                        logging.warning(f"Rate limit error for thread {self._thread.id}: {e}")
                        raise RateLimitException(f"Rate limit reached: {e}")
                    else:
                        logging.error(f"HTTP error retrieving last message for thread {self._thread.id}: {e}")
                        raise e

        # This should never be reached due to stop_after_attempt, but just in case
        raise Exception("Failed to get message after all retries")

    async def create_get_thread(self):
        """Create a new thread or retrieve one for the agent."""
        try:
            assert self._agent_client
            if self._thread_id:
                self._thread = await self._agent_client.threads.get(self._thread_id)
                logging.debug(f"Using existing thread ID: {self._thread.id}")
            elif not self._thread and not self._thread_id:
                self._thread = await self._agent_client.threads.create()
                logging.debug(f"Thread created with ID: {self._thread.id}")

        except HttpResponseError as e:
            logging.error(f"Error creating or getting thread: {e}")
            raise e

    async def invoke(self, input: str | None):
        """ Function to get response from the agent."""
        try:
            retries = 0

            # Initialize the client first
            await self._initialize_client()

            assert self._agent_client is not None
            assert self._agent_id is not None
            await self.create_get_thread()
            assert self._thread is not None
            token_usage = []

            if input is None:
                raise ValueError("Input cannot be None")

            try:
                await self._agent_client.get_agent(self._agent_id)
            except Exception as e:
                logging.error(f"Error retrieving agent: {e}")
                raise Exception(f"Error retrieving agent: {e}")

            try:
                await self._agent_client.messages.create(
                    thread_id=self._thread.id,
                    role=MessageRole.USER,
                    content=input,
                )
            except HttpResponseError as e:
                logging.error(f"Error sending message for thread {self._thread.id}: {e}")
                raise e

            token_usage_response, message_res, retries_answer = await self._retryable_call_to_foundry(self._agent_id)
            retries += retries_answer

            token_usage += [token_usage_response] if token_usage_response else []

            citations = None
            if message_res.text_messages[0].text.annotations:
                citations = [Citation(
                    type=citation.type or None,
                    position_in_response=citation.text or None,
                    citation_range_in_file=CitationRangeFile(
                        start=citation.start_index or 0,
                        end=citation.end_index or 0
                    ) if citation.start_index is not None and citation.end_index is not None else None,
                    citationTitle=None,
                    citationUrl=citation.file_citation.file_id,
                    abstract=None
                ) for citation in message_res.text_messages[0].text.annotations]

            response = ConversationChatResponse(
                task_id=message_res.run_id,
                task_status=message_res.status or "completed",
                agent_id=message_res.agent_id,
                content=message_res.text_messages[0].text.value,
                citations=citations,
                retries=retries,
                datetime=datetime_factory(),
            )

            return response, token_usage, self._thread.id
        except Exception as e:
            logging.error(f"Error getting agent response: {e}")
            raise e

    async def close(self):
        """Close the agent client."""
        if self._project_client:
            await self._project_client.close()
            logging.debug("Project client closed successfully")
        if self._agent_client:
            # The agent client is part of the project client, so it should be closed with it
            logging.debug("Agent client closed successfully")
        else:
            logging.warning("Project client was not initialized, nothing to close")
