"""
Attachment Model

Defines file attachments for documents, certificates, etc.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Attachment(Base):
    """File attachment metadata."""
    
    __tablename__ = "attachments"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    
    # Original file info
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Storage info
    storage_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    storage_type: Mapped[str] = mapped_column(String(20), default="local", nullable=False)
    
    # Entity association
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    
    # Categorization
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Security
    checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    antivirus_scanned: Mapped[bool] = mapped_column(default=False, nullable=False)
    antivirus_result: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Audit
    uploaded_by_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    # Relationships
    uploaded_by: Mapped["User"] = relationship("User")
    
    @property
    def size_kb(self) -> float:
        """Get file size in KB."""
        return self.size_bytes / 1024
    
    @property
    def size_mb(self) -> float:
        """Get file size in MB."""
        return self.size_bytes / (1024 * 1024)
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        original_filename = self.__dict__.get("original_filename", "<unloaded>")
        return f"<Attachment(id={id_}, filename={original_filename})>"
