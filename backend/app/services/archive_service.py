"""
Archive Service

Handles quarterly data archival:
- Exports transactions, audit logs, transfers, purchase indents,
  calibration records, maintenance records, notification logs, and jobs
  for a given date range into an Excel workbook + optional PDF ZIP bundle.
- Emails the archive bundle to GM/CEO recipients.
- Called by the scheduler for automatic 3-month archival and can be
  triggered manually via the API.
"""

import io
import hashlib
import json
import os
import zipfile
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_factory

logger = get_logger(__name__)

ARCHIVE_FORMAT_VERSION = 1
REQUIRED_WORKBOOK_SHEETS = {
    "Summary", "Transactions", "Audit Logs", "Transfers", "Purchase Indents",
    "Calibration Records", "Maintenance Records", "Jobs", "Notification Log",
}


def verify_archive(archive_bytes: bytes) -> dict:
    """Verify ZIP integrity, the manifest checksums and workbook readability."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
            corrupt_member = zf.testzip()
            if corrupt_member:
                raise ValueError(f"Archive member is corrupt: {corrupt_member}")
            manifest_names = [name for name in zf.namelist() if name.endswith("/manifest.json")]
            if len(manifest_names) != 1:
                raise ValueError("Archive must contain exactly one manifest.json")
            manifest = json.loads(zf.read(manifest_names[0]))
            if manifest.get("format_version") != ARCHIVE_FORMAT_VERSION:
                raise ValueError("Unsupported archive format version")
            expected_files = manifest.get("files")
            if not isinstance(expected_files, dict) or not expected_files:
                raise ValueError("Archive manifest has no file checksums")
            for name, expected_hash in expected_files.items():
                if name not in zf.namelist():
                    raise ValueError(f"Archive member is missing: {name}")
                actual_hash = hashlib.sha256(zf.read(name)).hexdigest()
                if actual_hash != expected_hash:
                    raise ValueError(f"Checksum mismatch for archive member: {name}")
            workbook_names = [name for name in expected_files if name.endswith("archive_data.xlsx")]
            if len(workbook_names) != 1:
                raise ValueError("Archive must contain exactly one data workbook")
            workbook = load_workbook(io.BytesIO(zf.read(workbook_names[0])), read_only=True)
            missing_sheets = REQUIRED_WORKBOOK_SHEETS.difference(workbook.sheetnames)
            if missing_sheets:
                raise ValueError(f"Archive workbook is missing sheets: {sorted(missing_sheets)}")
            workbook.close()
            return manifest
    except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError("Archive is not a valid verifiable ZIP bundle") from exc

# ---------------------------------------------------------------------------
# Styling helpers
# ---------------------------------------------------------------------------

_HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
_SUMMARY_FILL = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
_SUMMARY_FONT = Font(color="FFFFFF", bold=True, size=11)
_ALT_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")


def _write_sheet(ws, headers: List[str], rows: List[List]) -> None:
    """Write a styled header row + data rows to a worksheet."""
    ws.append(headers)
    for col_idx, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    for row_idx, row in enumerate(rows, start=2):
        ws.append(row)
        if row_idx % 2 == 0:
            for col_idx in range(1, len(headers) + 1):
                ws.cell(row=row_idx, column=col_idx).fill = _ALT_FILL

    # Auto-width (approximate)
    for col in ws.columns:
        max_len = max((len(str(cell.value)) if cell.value else 0) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 50)


def _fmt(value) -> str:
    """Format a value for Excel output."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else value.strftime("%Y-%m-%d")
    return str(value)


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

async def _fetch_transactions(db: AsyncSession, start: datetime, end: datetime) -> List[List]:
    from app.models.transaction import Transaction
    from app.models.item import Item
    from app.models.location import Location

    result = await db.execute(
        select(Transaction)
        .options(selectinload(Transaction.item), selectinload(Transaction.location))
        .where(and_(Transaction.transaction_date >= start, Transaction.transaction_date <= end))
        .order_by(Transaction.transaction_date)
    )
    rows = []
    for t in result.scalars().unique().all():
        rows.append([
            _fmt(t.id), _fmt(t.transaction_date), _fmt(t.transaction_type),
            _fmt(t.item.sku if t.item else None), _fmt(t.item.name if t.item else None),
            _fmt(t.location.name if t.location else None), _fmt(t.quantity),
            _fmt(t.unit_cost), _fmt(t.total_cost), _fmt(t.reference_number),
            _fmt(t.reference_type), _fmt(t.reason), _fmt(t.notes),
        ])
    return rows


async def _fetch_audit_logs(db: AsyncSession, start: datetime, end: datetime) -> List[List]:
    from app.models.audit import AuditLog

    result = await db.execute(
        select(AuditLog)
        .where(and_(AuditLog.occurred_at >= start, AuditLog.occurred_at <= end))
        .order_by(AuditLog.occurred_at)
    )
    rows = []
    for a in result.scalars().all():
        rows.append([
            _fmt(a.id), _fmt(a.occurred_at), _fmt(a.user_email), _fmt(a.user_role),
            _fmt(a.action), _fmt(a.resource_type), _fmt(a.resource_id),
            _fmt(a.http_method), _fmt(a.http_path), _fmt(a.status), _fmt(a.error_message),
        ])
    return rows


async def _fetch_transfers(db: AsyncSession, start: datetime, end: datetime) -> List[List]:
    from app.models.transfer import Transfer
    from app.models.location import Location

    result = await db.execute(
        select(Transfer)
        .options(selectinload(Transfer.from_location), selectinload(Transfer.to_location))
        .where(and_(Transfer.requested_date >= start.date(), Transfer.requested_date <= end.date()))
        .order_by(Transfer.requested_date)
    )
    rows = []
    for t in result.scalars().unique().all():
        rows.append([
            _fmt(t.id), _fmt(t.transfer_number), _fmt(t.requested_date), _fmt(t.status),
            _fmt(t.transfer_type), _fmt(t.priority),
            _fmt(t.from_location.name if t.from_location else None),
            _fmt(t.to_location.name if t.to_location else None),
            _fmt(t.approved_at), _fmt(t.shipped_at), _fmt(t.received_at),
            _fmt(t.return_date), _fmt(t.request_notes), _fmt(t.rejection_reason),
        ])
    return rows


async def _fetch_purchase_indents(db: AsyncSession, start: datetime, end: datetime) -> List[List]:
    from app.models.purchase_indent import PurchaseIndent

    result = await db.execute(
        select(PurchaseIndent)
        .options(
            selectinload(PurchaseIndent.requesting_location),
            selectinload(PurchaseIndent.supplying_location),
        )
        .where(and_(PurchaseIndent.indent_date >= start.date(), PurchaseIndent.indent_date <= end.date()))
        .order_by(PurchaseIndent.indent_date)
    )
    rows = []
    for p in result.scalars().unique().all():
        rows.append([
            _fmt(p.id), _fmt(p.indent_number), _fmt(p.indent_date), _fmt(p.status),
            _fmt(p.requesting_location.name if p.requesting_location else None),
            _fmt(p.supplying_location.name if p.supplying_location else None),
            _fmt(p.required_by_date), _fmt(p.approved_at),
            _fmt(p.purpose), _fmt(p.notes), _fmt(p.rejection_reason),
        ])
    return rows


async def _fetch_calibration_records(db: AsyncSession, start: datetime, end: datetime) -> List[List]:
    from app.models.calibration import CalibrationRecord

    result = await db.execute(
        select(CalibrationRecord)
        .where(and_(CalibrationRecord.performed_at >= start.date(), CalibrationRecord.performed_at <= end.date()))
        .order_by(CalibrationRecord.performed_at)
    )
    rows = []
    for c in result.scalars().all():
        rows.append([
            _fmt(c.id), _fmt(c.certificate_number), _fmt(c.performed_at), _fmt(c.due_at),
            _fmt(c.performed_by), _fmt(c.calibration_lab), _fmt(c.result),
            _fmt(c.as_found_condition), _fmt(c.as_left_condition), _fmt(c.notes),
        ])
    return rows


async def _fetch_maintenance_records(db: AsyncSession, start: datetime, end: datetime) -> List[List]:
    from app.models.maintenance import MaintenanceRecord

    result = await db.execute(
        select(MaintenanceRecord)
        .where(and_(MaintenanceRecord.scheduled_at >= start, MaintenanceRecord.scheduled_at <= end))
        .order_by(MaintenanceRecord.scheduled_at)
    )
    rows = []
    for m in result.scalars().all():
        rows.append([
            _fmt(m.id), _fmt(m.work_order_number), _fmt(m.maintenance_type),
            _fmt(m.scheduled_at), _fmt(m.started_at), _fmt(m.completed_at),
            _fmt(m.description), _fmt(m.work_performed), _fmt(m.result),
            _fmt(m.labor_hours), _fmt(m.labor_cost), _fmt(m.parts_cost), _fmt(m.notes),
        ])
    return rows


async def _fetch_jobs(db: AsyncSession, start: datetime, end: datetime) -> List[List]:
    from app.models.job import Job

    result = await db.execute(
        select(Job)
        .options(selectinload(Job.location))
        .where(and_(Job.job_date >= start.date(), Job.job_date <= end.date()))
        .order_by(Job.job_date)
    )
    rows = []
    for j in result.scalars().unique().all():
        rows.append([
            _fmt(j.id), _fmt(j.job_number), _fmt(j.job_date), _fmt(j.status),
            _fmt(j.customer), _fmt(j.job_name), _fmt(j.method),
            _fmt(j.location.name if j.location else None),
            _fmt(j.quantity), _fmt(j.coverage), _fmt(j.total),
            _fmt(j.person_name), _fmt(j.notes),
        ])
    return rows


async def _fetch_notifications(db: AsyncSession, start: datetime, end: datetime) -> List[List]:
    from app.models.notification import Notification

    result = await db.execute(
        select(Notification)
        .where(and_(Notification.created_at >= start, Notification.created_at <= end))
        .order_by(Notification.created_at)
    )
    rows = []
    for n in result.scalars().all():
        rows.append([
            _fmt(n.id), _fmt(n.created_at), _fmt(n.type if hasattr(n, "type") else None),
            _fmt(n.title if hasattr(n, "title") else None),
            _fmt(n.message if hasattr(n, "message") else None),
            _fmt(n.is_read if hasattr(n, "is_read") else None),
        ])
    return rows


async def _get_attachment_files(db: AsyncSession, start: datetime, end: datetime) -> List[Tuple[str, str]]:
    """Return list of (storage_key, original_filename) for attachments in range."""
    from app.models.attachment import Attachment

    result = await db.execute(
        select(Attachment.storage_key, Attachment.original_filename)
        .where(and_(Attachment.uploaded_at >= start, Attachment.uploaded_at <= end))
    )
    return result.all()


# ---------------------------------------------------------------------------
# Summary sheet builder
# ---------------------------------------------------------------------------

def _write_summary_sheet(ws, start: datetime, end: datetime, counts: dict) -> None:
    ws.title = "Summary"
    ws["A1"] = "ScienceTech-IMS — Quarterly Archive Report"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells("A1:C1")

    ws["A2"] = "Period"
    ws["B2"] = f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}"
    ws["A3"] = "Generated At"
    ws["B3"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    ws.append([])
    ws.append(["Sheet", "Record Count"])
    ws.cell(row=5, column=1).fill = _SUMMARY_FILL
    ws.cell(row=5, column=1).font = _SUMMARY_FONT
    ws.cell(row=5, column=2).fill = _SUMMARY_FILL
    ws.cell(row=5, column=2).font = _SUMMARY_FONT

    for i, (sheet_name, count) in enumerate(counts.items(), start=6):
        ws.cell(row=i, column=1, value=sheet_name)
        ws.cell(row=i, column=2, value=count)

    ws.column_dimensions["A"].width = 35
    ws.column_dimensions["B"].width = 30


# ---------------------------------------------------------------------------
# Main archive builder
# ---------------------------------------------------------------------------

async def build_archive(
    start: datetime,
    end: datetime,
    include_attachments: bool = True,
    session_factory=async_session_factory,
) -> bytes:
    """
    Build a ZIP archive containing:
    - archive_data.xlsx  (all tabular data in separate sheets)
    - attachments/       (actual uploaded files stored during the period)

    Returns raw ZIP bytes.
    """
    async with session_factory() as db:
        # Fetch all data
        tx_rows        = await _fetch_transactions(db, start, end)
        audit_rows     = await _fetch_audit_logs(db, start, end)
        transfer_rows  = await _fetch_transfers(db, start, end)
        indent_rows    = await _fetch_purchase_indents(db, start, end)
        cal_rows       = await _fetch_calibration_records(db, start, end)
        maint_rows     = await _fetch_maintenance_records(db, start, end)
        job_rows       = await _fetch_jobs(db, start, end)
        notif_rows     = await _fetch_notifications(db, start, end)
        attachment_files = await _get_attachment_files(db, start, end) if include_attachments else []

    # Build Excel workbook
    wb = Workbook()

    # Summary sheet first
    summary_ws = wb.active
    counts = {
        "Transactions": len(tx_rows),
        "Audit Logs": len(audit_rows),
        "Transfers": len(transfer_rows),
        "Purchase Indents": len(indent_rows),
        "Calibration Records": len(cal_rows),
        "Maintenance Records": len(maint_rows),
        "Jobs": len(job_rows),
        "Notification Log": len(notif_rows),
        "Attachments": len(attachment_files),
    }
    _write_summary_sheet(summary_ws, start, end, counts)

    # Transactions
    ws_tx = wb.create_sheet("Transactions")
    _write_sheet(ws_tx, [
        "ID", "Date", "Type", "SKU", "Item Name", "Location",
        "Qty", "Unit Cost", "Total Cost", "Reference #",
        "Reference Type", "Reason", "Notes",
    ], tx_rows)

    # Audit Logs
    ws_audit = wb.create_sheet("Audit Logs")
    _write_sheet(ws_audit, [
        "ID", "Timestamp", "User Email", "User Role",
        "Action", "Resource Type", "Resource ID",
        "HTTP Method", "HTTP Path", "Status", "Error Message",
    ], audit_rows)

    # Transfers
    ws_tr = wb.create_sheet("Transfers")
    _write_sheet(ws_tr, [
        "ID", "Transfer #", "Requested Date", "Status", "Type", "Priority",
        "From Location", "To Location",
        "Approved At", "Shipped At", "Received At", "Return Date",
        "Request Notes", "Rejection Reason",
    ], transfer_rows)

    # Purchase Indents
    ws_pi = wb.create_sheet("Purchase Indents")
    _write_sheet(ws_pi, [
        "ID", "Indent #", "Indent Date", "Status",
        "Requesting Location", "Supplying Location",
        "Required By", "Approved At", "Purpose", "Notes", "Rejection Reason",
    ], indent_rows)

    # Calibration
    ws_cal = wb.create_sheet("Calibration Records")
    _write_sheet(ws_cal, [
        "ID", "Certificate #", "Performed At", "Due At",
        "Performed By", "Lab", "Result",
        "As-Found Condition", "As-Left Condition", "Notes",
    ], cal_rows)

    # Maintenance
    ws_maint = wb.create_sheet("Maintenance Records")
    _write_sheet(ws_maint, [
        "ID", "Work Order #", "Type",
        "Scheduled At", "Started At", "Completed At",
        "Description", "Work Performed", "Result",
        "Labor Hours", "Labor Cost", "Parts Cost", "Notes",
    ], maint_rows)

    # Jobs
    ws_jobs = wb.create_sheet("Jobs")
    _write_sheet(ws_jobs, [
        "ID", "Job #", "Date", "Status",
        "Customer", "Job Name", "Method", "Location",
        "Qty", "Coverage", "Total", "Person Name", "Notes",
    ], job_rows)

    # Notification Log
    ws_notif = wb.create_sheet("Notification Log")
    _write_sheet(ws_notif, [
        "ID", "Created At", "Type", "Title", "Message", "Is Read",
    ], notif_rows)

    # Serialize workbook to bytes
    excel_buf = io.BytesIO()
    wb.save(excel_buf)
    excel_bytes = excel_buf.getvalue()

    # Build ZIP
    zip_buf = io.BytesIO()
    storage_base = os.path.abspath(settings.STORAGE_LOCAL_PATH)

    members = {}
    root = f"archive_{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"
    workbook_name = f"{root}/archive_data.xlsx"
    members[workbook_name] = excel_bytes

    if attachment_files:
        for storage_key, original_filename in attachment_files:
            file_path = os.path.join(storage_base, storage_key)
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"Required archive attachment is missing: {storage_key}")
            try:
                with open(file_path, "rb") as attachment_file:
                    members[f"{root}/attachments/{storage_key}_{original_filename}"] = attachment_file.read()
            except OSError as exc:
                raise OSError(f"Could not read required archive attachment: {storage_key}") from exc

    manifest = {
        "format_version": ARCHIVE_FORMAT_VERSION,
        "archive_kind": "audit_export_not_database_backup",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "record_counts": counts,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in members.items()},
    }

    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Add Excel file
        for name, data in members.items():
            zf.writestr(name, data)
        zf.writestr(
            f"{root}/manifest.json",
            json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"),
        )

    result = zip_buf.getvalue()
    verify_archive(result)
    return result


# ---------------------------------------------------------------------------
# Recipient resolution
# ---------------------------------------------------------------------------

async def get_archive_recipients(session_factory=async_session_factory) -> List[str]:
    """
    Return the list of email recipients for archive emails.
    Uses ARCHIVE_RECIPIENT_EMAILS from config if set,
    otherwise falls back to ADMIN and HEAD_OFFICE_MANAGER users in DB.
    """
    if settings.ARCHIVE_RECIPIENT_EMAILS:
        return list(settings.ARCHIVE_RECIPIENT_EMAILS)

    from app.models.user import User, UserRole

    async with session_factory() as db:
        result = await db.execute(
            select(User.email).where(
                User.is_active == True,  # noqa: E712
                User.role.in_([UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER]),
                User.email.isnot(None),
            )
        )
        emails = [row[0] for row in result.all() if row[0]]

    return emails


# ---------------------------------------------------------------------------
# Purge old records
# ---------------------------------------------------------------------------

async def purge_archived_records(
    before: datetime,
    session_factory=async_session_factory,
) -> dict:
    """
    Delete records older than `before` from all archivable tables.
    Returns counts of deleted rows per table.
    """
    from app.models.transaction import Transaction
    from app.models.audit import AuditLog
    from app.models.transfer import Transfer
    from app.models.purchase_indent import PurchaseIndent
    from app.models.calibration import CalibrationRecord
    from app.models.maintenance import MaintenanceRecord
    from app.models.job import Job
    from app.models.notification import Notification
    from sqlalchemy import delete

    deleted = {}

    async with session_factory() as db:
        # Transactions
        r = await db.execute(delete(Transaction).where(Transaction.transaction_date < before))
        deleted["transactions"] = r.rowcount

        # Audit logs are signed, append-only evidence and are never purged.
        deleted["audit_logs"] = 0

        # Transfers (use requested_date)
        r = await db.execute(delete(Transfer).where(Transfer.requested_date < before.date()))
        deleted["transfers"] = r.rowcount

        # Purchase indents
        r = await db.execute(delete(PurchaseIndent).where(PurchaseIndent.indent_date < before.date()))
        deleted["purchase_indents"] = r.rowcount

        # Calibration records
        r = await db.execute(delete(CalibrationRecord).where(CalibrationRecord.performed_at < before.date()))
        deleted["calibration_records"] = r.rowcount

        # Maintenance records
        r = await db.execute(delete(MaintenanceRecord).where(MaintenanceRecord.scheduled_at < before))
        deleted["maintenance_records"] = r.rowcount

        # Jobs
        r = await db.execute(delete(Job).where(Job.job_date < before.date()))
        deleted["jobs"] = r.rowcount

        # Notifications
        r = await db.execute(delete(Notification).where(Notification.created_at < before))
        deleted["notifications"] = r.rowcount

        await db.commit()

    logger.info(f"Purged archived records before {before}: {deleted}")
    return deleted
