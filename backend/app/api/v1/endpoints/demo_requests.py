"""Public endpoint for requesting an IMS demo without scheduling a meeting."""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import AppException
from app.services.demo_request_email_service import send_demo_request_email

router = APIRouter()


class DemoRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company_name: str = Field(min_length=2, max_length=160)
    company_address: str = Field(min_length=4, max_length=300)
    phone: str = Field(min_length=7, max_length=40)
    industry: str = Field(min_length=2, max_length=100)
    message: Optional[str] = Field(default=None, max_length=1200)
    requested_module: Optional[str] = Field(default=None, max_length=100)
    website: Optional[str] = Field(default=None, max_length=200)

    @field_validator("name", "company_name", "company_address", "phone", "industry")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field is required")
        return value

    @field_validator("message")
    @classmethod
    def trim_optional_message(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value

    @field_validator("requested_module")
    @classmethod
    def trim_optional_module(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value


@router.post("")
async def send_demo_request(request: DemoRequest):
    if request.website:
        return {"sent": True}
    sent = await run_in_threadpool(send_demo_request_email, request)
    if not sent:
        raise AppException(
            "The Amiro team could not receive the request right now. Please try again later.",
            error_code="DEMO_REQUEST_EMAIL_FAILED",
            status_code=503,
        )
    return {"sent": True}
