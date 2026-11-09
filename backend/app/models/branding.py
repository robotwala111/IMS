"""Application branding settings."""

from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppBranding(Base):
    """Single-row branding configuration used by UI and exports."""

    __tablename__ = "app_branding"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    app_name: Mapped[str] = mapped_column(String(100), nullable=False)
    logo_data_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

