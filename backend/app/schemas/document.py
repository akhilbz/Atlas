import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.document import DocumentStatus, SourceType


class DocumentResponse(BaseModel):
    """Public document representation — excludes raw content and internal file path."""

    id: uuid.UUID
    title: str
    source_type: SourceType
    status: DocumentStatus
    tags: list[Any]
    summary: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
