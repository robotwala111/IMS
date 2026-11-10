"""
Attachment Schemas

Pydantic schemas for file attachments.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel


class AttachmentBase(BaseModel):
    """Base attachment attributes."""
    description: Optional[str] = None


class AttachmentResponse(BaseModel):
    """Attachment response schema."""
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    uploaded_by_id: str
    uploaded_at: Optional[datetime] = None
    antivirus_scanned: bool
    antivirus_result: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AttachmentListResponse(BaseModel):
    """Paginated attachment list response."""
    items: List[AttachmentResponse]
    total: int
    page: int
    page_size: int
    pages: int
