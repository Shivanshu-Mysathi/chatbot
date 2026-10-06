import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator
from app.core.config import get_settings

class ChatRequest(BaseModel):
    session_id: uuid.UUID | None = None
    message: str
    @field_validator('message')
    @classmethod
    def validate_message(cls, value: str) -> str:
        s = get_settings()
        if not value.strip(): raise ValueError('Message cannot be empty.')
        if len(value) > s.max_message_length: raise ValueError(f'Message cannot exceed {s.max_message_length} characters.')
        return value
class ChatResponse(BaseModel):
    session_id: uuid.UUID
    message_id: uuid.UUID
    response: str
    model: str
    response_time_ms: int
class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    model: str | None
    response_time_ms: int | None
    created_at: datetime
