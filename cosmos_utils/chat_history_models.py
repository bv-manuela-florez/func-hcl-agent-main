from datetime import datetime
from pydantic import BaseModel
from cosmos_utils.cosmos_utils_orm import CosmosModel as CosmosModel
from typing import List, Literal


def datetime_factory():
    return str(datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"))


class Feedback(BaseModel):
    feedback: Literal[-1, 0, 1]  # -1: negative, 0: neutral, 1: positive
    user_id: str
    datetime: str = datetime_factory()


class User(BaseModel):
    user_id: str
    user_name: str | None = None
    user_email: str | None = None


class ConversationChatInput(BaseModel):
    """
    User input message sent to the agent.
    This model captures the user's message and associated metadata.
    """
    turn: str = 'user'
    channel: str = 'Teams'                  # Teams channel
    user_id: str | None = None              # None
    user: User | None = None                # None
    message: str                            # User message
    attachments: List[str] | None = None    # None
    datetime: str = datetime_factory()


class CitationRangeFile(BaseModel):
    start: int
    end: int


class Citation (BaseModel):
    type: str | None = None
    position_in_response: str | None = None
    citation_range_in_file: CitationRangeFile | None = None
    citationTitle: str | None = None
    citationUrl: str | None = None
    abstract: str | None = None


class TokenUsage(BaseModel):
    agent_id: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int


class SafetyAlert(BaseModel):
    threat_detection: bool = False
    reason: str | None = None


class ConversationChatResponse(BaseModel):
    """
    Agent output message sent to the user.
    This model captures the agent's message and associated metadata.
    """
    turn: str = 'assistant'
    task_id: str | None = None                  # thread_id
    task_status: str | None = None              # 'InProgress'
    context_id: str | None = None               # None
    agent: str = 'RAG agent'
    agent_tools: List[str] | None = None        # None
    content: str                                # Agent response
    citations: List[Citation] | None = None
    safety_alert: SafetyAlert | None = None     # None
    datetime: str = datetime_factory()
    retries: int = 0


class Fingerprint(BaseModel):
    user_id: str
    datetime: str = datetime_factory()


class ConversationChat(CosmosModel):
    """
    This model represents a conversation chat session.
    """
    # conversation_status: Literal["PendingRequest", "InProgress", "Completed"]
    session_id: str                                     # Thread_id
    user_id: str | None = None                          # None
    token_usage: List[TokenUsage] | None = None
    feedback: List[Feedback] | None = None              # None
    request: ConversationChatInput                      # User message
    response: ConversationChatResponse | None = None    # Agent response
    updated: Fingerprint | None = None                  # None

    class Meta:
        database_name: str = "aval_chat_history_db"
        partition_key: str = "session_id"
        container_name: str = "messages"
