"""Public Google Calendar availability and IMS demo booking endpoints."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, EmailStr, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import AppException
from app.services.demo_booking_email_service import send_demo_booking_email
from app.services.demo_calendar_service import DemoCalendarService

router = APIRouter()


class DemoBookingRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[EmailStr] = None
    company_name: Optional[str] = Field(default=None, max_length=160)
    company_address: Optional[str] = Field(default=None, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=40)
    industry: Optional[str] = Field(default=None, max_length=100)
    message: Optional[str] = Field(default=None, max_length=2000)
    requested_module: str = Field(default="IMS Demo", min_length=2, max_length=100)
    start_at: datetime
    website: Optional[str] = Field(default=None, max_length=200)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value: Optional[str]) -> str:
        if value and value.strip():
            return value.strip()
        return "Amiro Team Member"

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, value: Optional[str]) -> str:
        if value and value.strip():
            return value.strip()
        return settings.DEMO_BOOKING_ADMIN_EMAIL

    @field_validator("company_name", "company_address", "phone", "industry", mode="before")
    @classmethod
    def trim_optional_details(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value and value.strip() else None

    @field_validator("requested_module")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return "IMS Demo"
        return value

    @field_validator("message")
    @classmethod
    def trim_optional_message(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value


@router.get("/availability")
async def get_demo_availability(day: date = Query(..., description="Local date in YYYY-MM-DD format")):
    result = await run_in_threadpool(DemoCalendarService().availability, day)
    return result


@router.post("")
async def create_demo_booking(request: DemoBookingRequest):
    if request.website:
        return {"booked": True, "meeting_link": None, "email_notifications": {"amiro_notification_sent": False}}
    service = DemoCalendarService()
    booking = await run_in_threadpool(service.create_booking, request)
    email_sent = await run_in_threadpool(send_demo_booking_email, request, booking)
    booking["email_notifications"] = {"amiro_notification_sent": email_sent}
    booking["booked"] = True
    return booking
