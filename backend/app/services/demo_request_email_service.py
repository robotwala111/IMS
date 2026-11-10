"""Deliver client demo requests only to Amiro's configured mailbox."""

from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape
from pathlib import Path
import smtplib
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "amiro-logo.png"


def send_demo_request_email(request: Any) -> bool:
    if not settings.DEMO_REQUEST_EMAIL_ENABLED:
        logger.warning("Demo request email is disabled")
        return False
    if not all((settings.SMTP_HOST, settings.SMTP_USER, settings.SMTP_PASSWORD, settings.SMTP_FROM_EMAIL)):
        logger.warning("Demo request email is enabled but SMTP credentials are incomplete")
        return False

    recipient = settings.DEMO_REQUEST_ADMIN_EMAIL
    subject = f"IMS demo request — {request.name} | {request.company_name}"

    requirements = request.message or "Not provided"
    text_body = (
        "A client has requested an Amiro IMS demo. No meeting has been scheduled.\n\n"
        f"Client name: {request.name}\n"
        f"Client email: {request.email}\n"
        f"Company: {request.company_name}\n"
        f"Location address: {request.company_address}\n"
        f"Phone: {request.phone}\n"
        f"Industry: {request.industry}\n"
        f"Requested module: {request.requested_module or 'IMS demo'}\n"
        f"Project requirements: {requirements}"
    )
    rows = [
        ("Client name", request.name),
        ("Client email", request.email),
        ("Company", request.company_name),
        ("Location address", request.company_address),
        ("Phone", request.phone),
        ("Industry", request.industry),
        ("Requested module", request.requested_module or "IMS demo"),
        ("Project requirements", requirements),
    ]
    row_html = "".join(
        f'<p style="margin:10px 0"><b>{escape(label)}:</b> {escape(str(value)).replace(chr(10), "<br>")}</p>'
        for label, value in rows
    )
    html_body = (
        '<div style="max-width:620px;margin:20px auto;font:15px/1.6 Arial,sans-serif;color:#172033;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.08);border:1px solid #e2e8f0">'
        '<div style="padding:28px 28px 24px 28px;background:#101827;color:#fff">'
        '<div style="margin-bottom:18px">'
        '<img src="cid:amiro_logo" alt="Amiro Tech Solutions" width="240" height="76" style="display:block;border:0;outline:none;width:240px;max-width:100%;height:auto">'
        '</div>'
        '<h2 style="margin:0;color:#ffffff;font-size:22px;line-height:1.3;font-weight:700">New IMS demo request</h2></div>'
        f'<div style="padding:24px 28px">'
        f'<p style="margin-top:0">No meeting has been scheduled. The client details are below.</p>{row_html}</div></div>'
    )

    if LOGO_PATH.exists():
        message = MIMEMultipart("related")
        message["Subject"] = " ".join(subject.split())[:160]
        message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
        message["To"] = recipient

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
            logger.exception("Failed to attach amiro-logo image to demo request email")
    else:
        message = MIMEMultipart("alternative")
        message["Subject"] = " ".join(subject.split())[:160]
        message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
        message["To"] = recipient
        message.attach(MIMEText(text_body, "plain", "utf-8"))
        message.attach(MIMEText(html_body, "html", "utf-8"))

    password = settings.SMTP_PASSWORD.strip()
    try:
        if settings.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.login(settings.SMTP_USER, password)
                server.sendmail(settings.SMTP_FROM_EMAIL, [recipient], message.as_string())
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                if settings.SMTP_USE_TLS:
                    server.starttls()
                server.login(settings.SMTP_USER, password)
                server.sendmail(settings.SMTP_FROM_EMAIL, [recipient], message.as_string())
        return True
    except Exception:
        logger.exception("Demo request email delivery failed", recipient=recipient)
        return False
