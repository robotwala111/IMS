"""Send booked IMS demo details to Amiro and confirmation to the client."""

from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape
from pathlib import Path
import smtplib
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "amiro-logo.png"


def _format_meeting_time(start_str: str, tz_name: str) -> str:
    """Format ISO start string into a human-readable display."""
    try:
        dt = datetime.fromisoformat(start_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        return dt.strftime("%A, %d %b %Y at %I:%M %p")
    except Exception:
        return start_str


def _send_email_via_smtp(to_email: str, subject: str, text_body: str, html_body: str) -> bool:
    if LOGO_PATH.exists():
        message = MIMEMultipart("related")
        message["Subject"] = " ".join(subject.split())[:160]
        message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
        message["To"] = to_email

        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(text_body, "plain", "utf-8"))
        alt_part.attach(MIMEText(html_body, "html", "utf-8"))
        message.attach(alt_part)

        try:
            with open(LOGO_PATH, "rb") as f:
                img = MIMEImage(f.read(), _subtype="png")
                img.add_header("Content-ID", "<amiro_logo>")
                img.add_header("Content-Disposition", "inline", filename="amiro-logo.png")
                message.attach(img)
        except Exception:
            logger.exception("Failed to attach amiro-logo image to email")
    else:
        message = MIMEMultipart("alternative")
        message["Subject"] = " ".join(subject.split())[:160]
        message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
        message["To"] = to_email
        message.attach(MIMEText(text_body, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))

    password = settings.SMTP_PASSWORD.strip()
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            server.login(settings.SMTP_USER, password)
            server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], message.as_string())
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, password)
            server.sendmail(settings.SMTP_FROM_EMAIL, [to_email], message.as_string())
    return True


def send_demo_booking_email(request: Any, booking: dict[str, Any]) -> bool:
    if not settings.DEMO_BOOKING_EMAIL_ENABLED:
        logger.warning("Demo booking detail email is disabled")
        return False
    if not all((settings.SMTP_HOST, settings.SMTP_USER, settings.SMTP_PASSWORD, settings.SMTP_FROM_EMAIL)):
        logger.warning("Demo booking email is enabled but SMTP credentials are incomplete")
        return False

    admin_email = settings.DEMO_BOOKING_ADMIN_EMAIL
    client_email = str(request.email).strip()
    timezone_name = booking.get("timezone", settings.DEMO_BOOKING_TIMEZONE)
    raw_start = booking.get("start", "")
    formatted_time = _format_meeting_time(raw_start, timezone_name)
    meeting_link = booking.get("meeting_link") or "Meeting link will be shared shortly."

    # 1. Prepare Admin Notification Email
    company_name = getattr(request, "company_name", None) or ""
    phone = getattr(request, "phone", None) or ""
    company_address = getattr(request, "company_address", None) or ""
    industry = getattr(request, "industry", None) or ""

    admin_subject = f"IMS demo booked — {request.name}"
    if company_name:
        admin_subject += f" | {company_name}"

    admin_details = [
        ("Client name", request.name),
        ("Client email", client_email),
    ]
    if company_name:
        admin_details.append(("Company name", company_name))
    if phone:
        admin_details.append(("Contact number", phone))
    if company_address:
        admin_details.append(("Location address", company_address))
    if industry:
        admin_details.append(("Industry", industry))

    admin_details.extend([
        ("Requested modules", request.requested_module),
        ("Project requirements", request.message or "Not provided"),
        ("Meeting time", f"{formatted_time} ({timezone_name})"),
        ("Google Meet", meeting_link),
    ])

    admin_text = "A new IMS demo has been booked.\n\n" + "\n".join(f"{l}: {v}" for l, v in admin_details)
    admin_rows = "".join(
        f'<p style="margin:10px 0"><b>{escape(l)}:</b> {escape(str(v)).replace(chr(10), "<br>")}</p>'
        for l, v in admin_details
    )
    admin_html = (
        '<div style="max-width:620px;margin:20px auto;font:15px/1.6 Arial,sans-serif;color:#172033;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.08);border:1px solid #e2e8f0">'
        '<div style="padding:28px 28px 24px 28px;background:#101827;color:#fff">'
        '<div style="margin-bottom:18px">'
        '<img src="cid:amiro_logo" alt="Amiro Tech Solutions" width="240" height="76" style="display:block;border:0;outline:none;width:240px;max-width:100%;height:auto">'
        '</div>'
        '<h2 style="margin:0;color:#ffffff;font-size:22px;line-height:1.3;font-weight:700">New IMS Demo Booked</h2></div>'
        f'<div style="padding:24px 28px">{admin_rows}</div></div>'
    )

    # 2. Prepare Client Confirmation Email
    client_subject = f"Your Amiro IMS Demo Appointment is Confirmed — {formatted_time}"
    client_text_lines = [
        f"Hello {request.name},",
        "",
        "Thank you for booking a product demo of Amiro Tech Solutions IMS.",
        "",
        "Appointment Details:",
        f"- Date & Time: {formatted_time} ({timezone_name})",
        f"- Module: {request.requested_module}",
    ]
    if company_name:
        client_text_lines.append(f"- Company: {company_name}")
    client_text_lines.extend([
        f"- Google Meet: {meeting_link}",
        "",
        "Join the video meeting using the Google Meet link above at the scheduled time.",
        "",
        "Best regards,",
        "The Amiro Team",
        "Amiro Tech Solutions",
    ])
    client_text = "\n".join(client_text_lines)

    meet_button_html = (
        f'<p style="margin:24px 0">'
        f'<a href="{escape(meeting_link)}" style="display:inline-block;padding:12px 24px;'
        f'background:#2563eb;color:#ffffff;text-decoration:none;font-weight:bold;border-radius:6px">'
        f'Join Google Meet</a></p>'
        if meeting_link.startswith("http") else ""
    )
    client_meta_html = (
        f'<p style="margin:6px 0"><b>Company:</b> {escape(company_name)}</p>'
        if company_name else ""
    )
    client_html = (
        '<div style="max-width:620px;margin:20px auto;font:15px/1.6 Arial,sans-serif;color:#172033;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.08);border:1px solid #e2e8f0">'
        '<div style="padding:28px 28px 24px 28px;background:#101827;color:#fff">'
        '<div style="margin-bottom:18px">'
        '<img src="cid:amiro_logo" alt="Amiro Tech Solutions" width="240" height="76" style="display:block;border:0;outline:none;width:240px;max-width:100%;height:auto">'
        '</div>'
        '<h2 style="margin:0;color:#ffffff;font-size:22px;line-height:1.3;font-weight:700">Your Demo Appointment is Confirmed</h2></div>'
        '<div style="padding:26px 28px">'
        f'<p style="margin-top:0">Hello <b>{escape(request.name)}</b>,</p>'
        '<p>Thank you for booking an IMS product demonstration with Amiro Tech Solutions. We look forward to meeting with you.</p>'
        '<div style="background:#f8fafc;padding:18px 22px;border-radius:8px;margin:20px 0;border-left:4px solid #f4b000;border:1px solid #e2e8f0;border-left-width:4px">'
        f'<p style="margin:6px 0"><b>Date & Time:</b> {escape(formatted_time)} ({escape(timezone_name)})</p>'
        f'<p style="margin:6px 0"><b>Requested Module:</b> {escape(request.requested_module)}</p>'
        f'{client_meta_html}'
        f'<p style="margin:6px 0"><b>Google Meet Link:</b> <a href="{escape(meeting_link)}" style="color:#2563eb;word-break:break-all">{escape(meeting_link)}</a></p>'
        '</div>'
        f'{meet_button_html}'
        '<p style="color:#64748b;font-size:13px;margin-top:24px;border-top:1px solid #e2e8f0;padding-top:16px;line-height:1.5">'
        'If you need to reschedule or have questions prior to the meeting, reply to this email or reach us at '
        f'<a href="mailto:{escape(settings.SMTP_FROM_EMAIL)}" style="color:#2563eb">{escape(settings.SMTP_FROM_EMAIL)}</a>.</p>'
        '</div></div>'
    )

    admin_sent = False
    client_sent = False

    # Send to Admin
    try:
        _send_email_via_smtp(admin_email, admin_subject, admin_text, admin_html)
        admin_sent = True
        logger.info("Demo booking notification sent to admin", recipient=admin_email)
    except Exception:
        logger.exception("Failed to send demo booking notification to admin", recipient=admin_email)

    # Send to Client (if different from admin, or even if same, we already sent admin notification)
    if client_email and client_email.lower() != admin_email.lower():
        try:
            _send_email_via_smtp(client_email, client_subject, client_text, client_html)
            client_sent = True
            logger.info("Demo booking confirmation sent to client", recipient=client_email)
        except Exception:
            logger.exception("Failed to send demo booking confirmation to client", recipient=client_email)
    else:
        # Client is the admin
        client_sent = admin_sent

    return admin_sent or client_sent
