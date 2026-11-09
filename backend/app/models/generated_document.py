"""Generated document storage.

Stores generated compliance document copies such as PI, DC, registers, and
monthly ZIP bundles. Business source records remain in their own tables.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GeneratedDocument(Base):
    """Generated file copy kept for download/email retention."""

    __tablename__ = "generated_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reference_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    related_entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    related_entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    generated_by_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    email_batch_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    emailed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    generated_by = relationship("User")
