import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: str | None
    title: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
class SessionDetail(SessionOut): pass
