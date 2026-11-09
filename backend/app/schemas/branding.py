"""Branding schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BrandingResponse(BaseModel):
    id: str
    company_name: str
    app_name: str
    logo_data_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BrandingUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=1, max_length=255)
    app_name: Optional[str] = Field(None, min_length=1, max_length=100)
    logo_data_url: Optional[str] = None

