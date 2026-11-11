"""Google Calendar availability and IMS demo booking operations."""

from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.exceptions import AppException

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"

# 90-minute demo slot windows requested:
# 10:30 AM - 12:00 PM
# 1:00 PM - 2:30 PM
# 3:00 PM - 4:30 PM
DEMO_SLOT_WINDOWS: list[tuple[time, time, str]] = [
    (time(10, 30), time(12, 0), "10:30 AM - 12:00 PM"),
    (time(13, 0), time(14, 30), "1:00 PM - 2:30 PM"),
    (time(15, 0), time(16, 30), "3:00 PM - 4:30 PM"),
]


class DemoCalendarService:
    def __init__(self) -> None:
        self.timezone = ZoneInfo(settings.DEMO_BOOKING_TIMEZONE)
        self.calendar_id = settings.GOOGLE_CALENDAR_ID

    def _check_configuration(self) -> None:
        required = (
            settings.GOOGLE_CALENDAR_CLIENT_ID,
            settings.GOOGLE_CALENDAR_CLIENT_SECRET,
            settings.GOOGLE_CALENDAR_REFRESH_TOKEN,
            settings.GOOGLE_CALENDAR_ID,
        )
        if not all(value.strip() for value in required):
            raise AppException(
                "Demo scheduling is not connected yet. Please contact amirotechsolutions.sales@gmail.com.",
                error_code="DEMO_CALENDAR_NOT_CONFIGURED",
                status_code=503,
            )

    def _access_token(self) -> str:
        self._check_configuration()
        try:
            response = httpx.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CALENDAR_CLIENT_SECRET,
                    "refresh_token": settings.GOOGLE_CALENDAR_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
                timeout=20,
            )
            if response.status_code >= 400:
                raise AppException(
                    "Google Calendar authorization failed. Please contact the Amiro team.",
                    error_code="DEMO_CALENDAR_AUTH_FAILED",
                    status_code=503,
                )
            return response.json()["access_token"]
        except AppException:
            raise
        except Exception as exc:
            raise AppException(
                "Google Calendar could not be reached. Please try again later.",
                error_code="DEMO_CALENDAR_UNREACHABLE",
                status_code=503,
            ) from exc

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{GOOGLE_CALENDAR_API}{path}"
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            response = httpx.request(method, url, headers=headers, timeout=25, **kwargs)
            if response.status_code == 409:
                raise AppException(
                    "This slot is already booked. Can you please select other slot timings?",
                    error_code="DEMO_SLOT_UNAVAILABLE",
                    status_code=409,
                )
            if response.status_code >= 400:
                raise AppException(
                    "Google Calendar could not complete the request. Please try again later.",
                    error_code="DEMO_CALENDAR_UNREACHABLE",
                    status_code=503,
                )
            return response.json()
        except AppException:
            raise
        except Exception as exc:
            raise AppException(
                "Google Calendar could not be reached. Please try again later.",
                error_code="DEMO_CALENDAR_UNREACHABLE",
                status_code=503,
            ) from exc

    def _busy(self, day: date) -> list[tuple[datetime, datetime]]:
        start = datetime.combine(day, time.min, tzinfo=self.timezone)
        end = start + timedelta(days=1)
        result = self._request(
            "POST",
            "/freeBusy",
            json={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "timeZone": settings.DEMO_BOOKING_TIMEZONE,
                "items": [{"id": self.calendar_id}],
            },
        )
        calendars = result.get("calendars", {})
        busy = calendars.get(self.calendar_id, {}).get("busy", [])
        return [
            (datetime.fromisoformat(item["start"].replace("Z", "+00:00")).astimezone(self.timezone),
             datetime.fromisoformat(item["end"].replace("Z", "+00:00")).astimezone(self.timezone))
            for item in busy
        ]

    def availability(self, day: date) -> dict[str, Any]:
        today = datetime.now(self.timezone).date()
        if day <= today or day > today + timedelta(days=settings.DEMO_BOOKING_DAYS_AHEAD):
            raise AppException(
                f"Choose a date from tomorrow through the next {settings.DEMO_BOOKING_DAYS_AHEAD} days. Same-day bookings are not available.",
                error_code="DEMO_DATE_OUT_OF_RANGE",
                status_code=400,
            )

        if day.weekday() == 6:  # Sunday is blocked
            raise AppException(
                "Sundays are closed for demo appointments. Please choose another date (Monday to Saturday).",
                error_code="DEMO_SUNDAY_UNAVAILABLE",
                status_code=400,
            )

        busy = self._busy(day)
        now = datetime.now(self.timezone)
        slots = []
        for start_t, end_t, label in DEMO_SLOT_WINDOWS:
            slot_start = datetime.combine(day, start_t, tzinfo=self.timezone)
            slot_end = datetime.combine(day, end_t, tzinfo=self.timezone)
            if slot_start > now and not any(slot_start < b_end and slot_end > b_start for b_start, b_end in busy):
                slots.append({
                    "start": slot_start.isoformat(),
                    "end": slot_end.isoformat(),
                    "label": label,
                })
        return {"day": day.isoformat(), "timezone": settings.DEMO_BOOKING_TIMEZONE, "slots": slots}

    def create_booking(self, request: Any) -> dict[str, Any]:
        start = request.start_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=self.timezone)
        start = start.astimezone(self.timezone)

        if start.date().weekday() == 6:
            raise AppException(
                "Sundays are closed for demo appointments. Please choose Monday through Saturday.",
                error_code="DEMO_SUNDAY_UNAVAILABLE",
                status_code=400,
            )

        matching_window = next((w for w in DEMO_SLOT_WINDOWS if w[0] == start.time()), None)
        if not matching_window:
            raise AppException(
                "Choose one of the available demo times (10:30 AM - 12:00 PM, 1:00 PM - 2:30 PM, 3:00 PM - 4:30 PM).",
                error_code="INVALID_DEMO_SLOT",
                status_code=400,
            )

        slot_end = datetime.combine(start.date(), matching_window[1], tzinfo=self.timezone)
        slot_label = matching_window[2]

        availability = self.availability(start.date())
        if not any(slot["start"] == start.isoformat() for slot in availability["slots"]):
            raise AppException(
                "This slot is already booked. Can you please select other slot timings?",
                error_code="DEMO_SLOT_UNAVAILABLE",
                status_code=409,
            )

        company_label = f" ({request.company_name})" if getattr(request, "company_name", None) else ""
        desc_lines = [
            "Amiro Tech Solutions IMS product demonstration.",
            f"Timing: {slot_label} ({settings.DEMO_BOOKING_TIMEZONE})",
            "",
            f"Client Name: {request.name}",
            f"Client Email: {request.email}",
        ]
        if getattr(request, "company_name", None):
            desc_lines.append(f"Company: {request.company_name}")
        if getattr(request, "phone", None):
            desc_lines.append(f"Contact Number: {request.phone}")
        if getattr(request, "company_address", None):
            desc_lines.append(f"Location Address: {request.company_address}")
        if getattr(request, "industry", None):
            desc_lines.append(f"Industry: {request.industry}")
        desc_lines.append(f"Requested Module: {request.requested_module}")
        desc_lines.append(f"Project Requirements: {request.message or 'None specified'}")

        event = {
            "id": f"imsdemo{start.strftime('%Y%m%d%H%M')}",
            "summary": f"Amiro Tech Solutions IMS demo — {request.name}{company_label}",
            "description": "\n".join(desc_lines),
            "start": {"dateTime": start.isoformat(), "timeZone": settings.DEMO_BOOKING_TIMEZONE},
            "end": {"dateTime": slot_end.isoformat(), "timeZone": settings.DEMO_BOOKING_TIMEZONE},
            "attendees": [{"email": str(request.email), "displayName": request.name}],
            "conferenceData": {
                "createRequest": {
                    "requestId": str(uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        created = self._request(
            "POST",
            f"/calendars/{quote(self.calendar_id, safe='')}/events",
            params={"conferenceDataVersion": 1, "sendUpdates": "all"},
            json=event,
        )
        meeting_link = created.get("hangoutLink")
        if not meeting_link:
            meeting_link = next((
                point.get("uri")
                for point in created.get("conferenceData", {}).get("entryPoints", [])
                if point.get("entryPointType") == "video"
            ), None)
        return {
            "id": created.get("id"),
            "start": created.get("start", {}).get("dateTime", start.isoformat()),
            "end": created.get("end", {}).get("dateTime", slot_end.isoformat()),
            "timezone": settings.DEMO_BOOKING_TIMEZONE,
            "meeting_link": meeting_link,
            "slot_label": slot_label,
        }
