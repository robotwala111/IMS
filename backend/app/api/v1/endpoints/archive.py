"""
Archive API Endpoints

Provides manual data export/archive functionality for ADMIN and HEAD_OFFICE_MANAGER users.

Endpoints:
  POST /archive/export          — Generate and download a ZIP archive for a date range
  POST /archive/send-email      — Generate archive and email it to GM/CEO recipients
  GET  /archive/next-schedule   — Show when the next automatic archive will run
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.v1.dependencies import CurrentUser, RoleChecker
from app.core.exceptions import AuthorizationError
from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import UserRole
from app.services.archive_service import build_archive, get_archive_recipients, verify_archive
from app.services.email_service import get_email_service

logger = get_logger(__name__)

router = APIRouter(prefix="/archive", tags=["Archive"])

# Only ADMIN and HEAD_OFFICE_MANAGER may access archive endpoints
_require_manager = RoleChecker(
    allowed_roles=[UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER]
)


@router.post(
    "/export",
    summary="Export archive as ZIP download",
    response_class=Response,
    dependencies=[Depends(_require_manager)],
)
async def export_archive(
    current_user: CurrentUser,
    start_date: str = Query(
        ...,
        description="Start date (inclusive) in YYYY-MM-DD format",
        examples=["2026-01-01"],
    ),
    end_date: str = Query(
        ...,
        description="End date (inclusive) in YYYY-MM-DD format",
        examples=["2026-03-31"],
    ),
    include_attachments: bool = Query(
        True,
        description="Include uploaded PDFs/files in the archive ZIP",
    ),
) -> Response:
    """
    Generate a ZIP archive for the specified date range and return it as a download.

    Contains:
    - archive_data.xlsx (transactions, audit logs, transfers, purchase indents,
      calibration records, maintenance records, jobs, notification log)
    - attachments/ directory (uploaded files created in the period)

    No records are purged — this is a read-only export.
    """
    try:
        period_start = datetime.strptime(start_date, "%Y-%m-%d")
        period_end = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if period_end < period_start:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date.")

    logger.info(
        f"Manual archive export requested by {current_user.email} "
        f"({period_start.date()} to {period_end.date()})"
    )

    zip_bytes = await build_archive(period_start, period_end, include_attachments=include_attachments)
    manifest = verify_archive(zip_bytes)

    period_label = f"{period_start.strftime('%Y%m%d')}-{period_end.strftime('%Y%m%d')}"
    filename = f"sciencetech_ims_archive_{period_label}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Archive-SHA256": __import__("hashlib").sha256(zip_bytes).hexdigest(),
            "X-Archive-Format-Version": str(manifest["format_version"]),
        },
    )


@router.post(
    "/send-email",
    summary="Generate archive and email it to GM/CEO recipients",
    dependencies=[Depends(_require_manager)],
)
async def send_archive_email(
    current_user: CurrentUser,
    start_date: str = Query(
        ...,
        description="Start date (inclusive) in YYYY-MM-DD format",
        examples=["2026-01-01"],
    ),
    end_date: str = Query(
        ...,
        description="End date (inclusive) in YYYY-MM-DD format",
        examples=["2026-03-31"],
    ),
    include_attachments: bool = Query(True),
) -> dict:
    """
    Generate a ZIP archive for the specified date range and email it to the configured
    GM/CEO recipients (ARCHIVE_RECIPIENT_EMAILS or ADMIN/HEAD_OFFICE_MANAGER users).
    No records are purged.
    """
    import smtplib
    from email import encoders
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not settings.ARCHIVE_EMAIL_ATTACHMENTS_ENABLED:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="Emailing archive attachments is disabled. Download the verified archive through the authenticated export endpoint.",
        )

    try:
        period_start = datetime.strptime(start_date, "%Y-%m-%d")
        period_end = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if period_end < period_start:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date.")

    logger.info(
        f"Manual archive email requested by {current_user.email} "
        f"({period_start.date()} to {period_end.date()})"
    )

    zip_bytes = await build_archive(period_start, period_end, include_attachments=include_attachments)
    verify_archive(zip_bytes)
    recipients = await get_archive_recipients()

    if not recipients:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail="No archive recipients configured. Set ARCHIVE_RECIPIENT_EMAILS in .env "
                   "or ensure ADMIN/HEAD_OFFICE_MANAGER users exist.",
        )

    period_label = f"{period_start.strftime('%Y%m%d')}-{period_end.strftime('%Y%m%d')}"
    filename = f"sciencetech_ims_archive_{period_label}.zip"

    email_service = get_email_service()

    # Send summary/delivery notification
    email_service.send_archive_delivery(
        to_emails=recipients,
        period_start=period_start,
        period_end=period_end,
        record_counts={},
        purged=False,
    )

    # Send ZIP as attachment
    if email_service.enabled and email_service.backend == "smtp":
        try:
            msg = MIMEMultipart()
            msg["Subject"] = f"[ScienceTech-IMS] Manual Archive — {period_label}"
            msg["From"] = f"{email_service.from_name} <{email_service.from_email}>"
            msg["To"] = ", ".join(recipients)
            msg.attach(MIMEText(
                f"Manual archive export requested by {current_user.name} ({current_user.email}).\n"
                f"Period: {start_date} to {end_date}\n\nPlease find the archive bundle attached.",
                "plain",
            ))

            part = MIMEBase("application", "zip")
            part.set_payload(zip_bytes)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            msg.attach(part)

            if email_service.smtp_port == 465:
                with smtplib.SMTP_SSL(email_service.smtp_host, email_service.smtp_port) as s:
                    if email_service.smtp_user:
                        s.login(email_service.smtp_user, email_service.smtp_password)
                    s.sendmail(email_service.from_email, recipients, msg.as_string())
            else:
                with smtplib.SMTP(email_service.smtp_host, email_service.smtp_port) as s:
                    s.starttls()
                    if email_service.smtp_user:
                        s.login(email_service.smtp_user, email_service.smtp_password)
                    s.sendmail(email_service.from_email, recipients, msg.as_string())

            logger.info(f"Manual archive ZIP emailed to {recipients}")
        except Exception as exc:
            logger.exception(f"Failed to email archive ZIP: {exc}")
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=f"Archive generated but email failed: {str(exc)}")
    else:
        logger.info(f"[CONSOLE] Email disabled — archive would be sent to {recipients}")

    return {
        "message": f"Archive generated and emailed to {len(recipients)} recipient(s)",
        "recipients": recipients,
        "period": {"start": start_date, "end": end_date},
        "filename": filename,
        "size_bytes": len(zip_bytes),
    }


@router.get(
    "/next-schedule",
    summary="Get next automatic archive schedule info",
    dependencies=[Depends(_require_manager)],
)
async def get_next_archive_schedule(current_user: CurrentUser) -> dict:
    """
    Returns when the next automatic quarterly archive will run,
    what period it will cover, and when the warning email will be sent.
    """
    from datetime import date

    today = date.today()
    retention_months = settings.ARCHIVE_RETENTION_MONTHS
    warning_days = settings.ARCHIVE_WARNING_DAYS

    quarter_months = sorted(set((m - 1) % 12 + 1 for m in [1, 1 + retention_months, 1 + retention_months * 2]))

    next_archive = None
    for month in quarter_months:
        candidate_year = today.year if month >= today.month else today.year + 1
        candidate = date(candidate_year, month, 1)
        if candidate > today:
            next_archive = candidate
            break
    if next_archive is None:
        next_archive = date(today.year + 1, quarter_months[0], 1)

    warning_date = next_archive - timedelta(days=warning_days)

    # Period covered
    period_end_dt = datetime(next_archive.year, next_archive.month, 1) - timedelta(seconds=1)
    start_month = (next_archive.month - retention_months - 1) % 12 + 1
    start_year = next_archive.year if next_archive.month > retention_months else next_archive.year - 1
    period_start_dt = datetime(start_year, start_month, 1)

    return {
        "next_archive_date": next_archive.isoformat(),
        "warning_email_date": warning_date.isoformat(),
        "period_covered": {
            "start": period_start_dt.date().isoformat(),
            "end": period_end_dt.date().isoformat(),
        },
        "retention_months": retention_months,
        "warning_days": warning_days,
        "days_until_archive": (next_archive - today).days,
        "days_until_warning": (warning_date - today).days,
    }
