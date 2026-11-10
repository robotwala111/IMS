"""
Job Schemas

Pydantic models for Job (Hold) feature.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobCreate(BaseModel):
    """Schema for creating a new job."""

    job_date: date
    customer: str = Field(..., min_length=1, max_length=255)
    job_name: str = Field(..., min_length=1, max_length=255)
    method: str = Field(..., min_length=1, max_length=50)
    quantity: int = Field(..., ge=0)
    coverage: Optional[str] = Field(None, max_length=100)
    total: int = Field(..., ge=0)
    person_name: str = Field(..., min_length=1, max_length=255)
    assigned_to_id: Optional[str] = None
    location_id: Optional[str] = None
    notes: Optional[str] = None


class JobUpdate(BaseModel):
    """Schema for updating a job (all fields optional)."""

    job_date: Optional[date] = None
    customer: Optional[str] = Field(None, max_length=255)
    job_name: Optional[str] = Field(None, max_length=255)
    method: Optional[str] = Field(None, max_length=50)
    quantity: Optional[int] = Field(None, ge=0)
    coverage: Optional[str] = Field(None, max_length=100)
    total: Optional[int] = Field(None, ge=0)
    person_name: Optional[str] = Field(None, max_length=255)
    assigned_to_id: Optional[str] = None
    location_id: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class JobCompleteRequest(BaseModel):
    """
    Schema submitted when a person marks a job as done.
    The total is auto-populated from the job, but accepted + reshoot + cut_films
    must sum to equal total before the job can be validated.
    """

    accepted: int = Field(..., ge=0)
    reshoot: int = Field(..., ge=0)
    cut_films_count: int = Field(..., ge=0, description="Number of cut films")
    cut_films: Optional[str] = Field(None, description="Optional cut-film details")


class JobResponse(BaseModel):
    """Job response schema."""

    id: str
    job_number: str
    job_date: date
    customer: str
    job_name: str
    method: str
    quantity: int
    coverage: Optional[str] = None
    total: int
    person_name: str
    assigned_to_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    location_id: Optional[str] = None
    location_name: Optional[str] = None
    status: str
    completed_by_id: Optional[str] = None
    completed_by_name: Optional[str] = None
    completed_at: Optional[datetime] = None
    accepted: Optional[int] = None
    reshoot: Optional[int] = None
    cut_films: Optional[str] = None
    cut_films_count: Optional[int] = None
    is_validated: bool = False
    notes: Optional[str] = None
    created_by_id: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
    """Paginated job list response."""

    items: List[JobResponse]
    total: int
    page: int
    page_size: int
    pages: int
