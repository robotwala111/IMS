"""Generated document schemas."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class GeneratedDocumentResponse(BaseModel):
    id: str
    document_type: str
    reference_number: str
    revision_number: int
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    filename: str
    content_type: str
    size_bytes: int
    generated_by_id: Optional[str] = None
    generated_at: datetime
    expires_at: Optional[datetime] = None
    email_batch_id: Optional[str] = None
    emailed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class GeneratedDocumentListResponse(BaseModel):
    items: List[GeneratedDocumentResponse]
    total: int


class MonthlyDocumentEmailResponse(BaseModel):
    sent: bool
    recipients: List[str]
    zip_files: List[str]
    document_count: int
    batch_id: str


class CleanupGeneratedDocumentsResponse(BaseModel):
    deleted_count: int
