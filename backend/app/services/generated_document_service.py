"""Generated document service."""

import csv
import io
import zipfile
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.branding import AppBranding
from app.models.generated_document import GeneratedDocument
from app.models.purchase_indent import PurchaseIndent
from app.models.transfer import Transfer, TransferStatus
from app.models.user import User, UserRole
from app.services.base_service import BaseService
from app.services.email_service import get_email_service
from app.services.purchase_indent_service import PurchaseIndentService
from app.services.report_service import ReportService
from app.services.transfer_service import TransferService


class GeneratedDocumentService(BaseService[GeneratedDocument]):
    """Create, store, email, and clean up generated document copies."""

    @property
    def model(self) -> type:
        return GeneratedDocument

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _expiry(self) -> datetime:
        return self._now() + timedelta(days=settings.GENERATED_DOCUMENT_RETENTION_DAYS)

    async def store_document(
        self,
        *,
        document_type: str,
        reference_number: str,
        filename: str,
        content_type: str,
        content: bytes,
        related_entity_type: Optional[str] = None,
        related_entity_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        generated_by_id: Optional[str] = None,
        email_batch_id: Optional[str] = None,
        notes: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> GeneratedDocument:
        """Store an immutable generated snapshot with a monotonic revision number."""
        query = select(GeneratedDocument).where(
            GeneratedDocument.document_type == document_type,
            GeneratedDocument.reference_number == reference_number,
            GeneratedDocument.filename == filename,
        )
        if related_entity_id:
            query = query.where(GeneratedDocument.related_entity_id == related_entity_id)
        result = await self.db.execute(query.order_by(GeneratedDocument.revision_number.desc()).limit(1))
        previous = result.scalar_one_or_none()
        now = self._now()
        doc = GeneratedDocument(
            id=self.generate_id(), document_type=document_type,
            reference_number=reference_number,
            revision_number=(previous.revision_number + 1) if previous else 1,
            filename=filename, content_type=content_type, size_bytes=len(content),
            content=content, related_entity_type=related_entity_type,
            related_entity_id=related_entity_id, period_start=period_start,
            period_end=period_end, generated_by_id=generated_by_id,
            generated_at=now, expires_at=expires_at or self._expiry(),
            email_batch_id=email_batch_id, notes=notes,
        )
        self.db.add(doc)

        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def list_documents(
        self,
        *,
        document_type: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[GeneratedDocument]:
        query = select(GeneratedDocument).order_by(GeneratedDocument.generated_at.desc())
        if document_type:
            query = query.where(GeneratedDocument.document_type == document_type)
        if start:
            query = query.where(GeneratedDocument.generated_at >= start)
        if end:
            query = query.where(GeneratedDocument.generated_at <= end)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def generate_and_store_pi_pdf(
        self,
        indent_id: str,
        *,
        generated_by_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> GeneratedDocument:
        service = PurchaseIndentService(self.db)
        indent = await service.get_by_id(indent_id)
        if not indent:
            raise NotFoundError(resource="PurchaseIndent", resource_id=indent_id)

        html = self._build_pi_html(indent)
        content, filename, content_type = self._html_to_document(
            html,
            self._safe_filename(indent.indent_number),
        )
        return await self.store_document(
            document_type="PI",
            reference_number=indent.indent_number,
            filename=filename,
            content_type=content_type,
            content=content,
            related_entity_type="purchase_indent",
            related_entity_id=indent.id,
            period_start=period_start,
            period_end=period_end,
            generated_by_id=generated_by_id,
        )

    async def generate_and_store_dc_pdf(
        self,
        transfer_id: str,
        *,
        generated_by_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> GeneratedDocument:
        transfer_service = TransferService(self.db)
        transfer = await transfer_service.get_by_id(transfer_id)
        if not transfer:
            raise NotFoundError(resource="Transfer", resource_id=transfer_id)
        if transfer.status not in [
            TransferStatus.APPROVED,
            TransferStatus.IN_TRANSIT,
            TransferStatus.RECEIVED,
            TransferStatus.PARTIALLY_RECEIVED,
        ]:
            raise BadRequestError(message="Delivery Challan is not available for this transfer status")

        dc_number = await transfer_service.ensure_dc_number(transfer)
        await self.db.commit()
        branding_result = await self.db.execute(
            select(AppBranding).where(AppBranding.id == "default")
        )
        branding = branding_result.scalar_one_or_none()
        html = self._build_dc_html(
            transfer,
            dc_number,
            company_name=branding.company_name if branding else "M/s Scientech Services",
            logo_data_url=branding.logo_data_url if branding else None,
        )
        content, filename, content_type = self._html_to_document(
            html,
            self._safe_filename(dc_number),
        )
        return await self.store_document(
            document_type="DC",
            reference_number=dc_number,
            filename=filename,
            content_type=content_type,
            content=content,
            related_entity_type="transfer",
            related_entity_id=transfer.id,
            period_start=period_start,
            period_end=period_end,
            generated_by_id=generated_by_id,
        )

    async def store_register_xlsx(
        self,
        *,
        document_type: str,
        reference_number: str,
        filename: str,
        content: bytes,
        generated_by_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> GeneratedDocument:
        return await self.store_document(
            document_type=document_type,
            reference_number=reference_number,
            filename=filename,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content=content,
            related_entity_type="register",
            period_start=period_start,
            period_end=period_end,
            generated_by_id=generated_by_id,
        )

    async def store_compliance_csv(
        self,
        *,
        reference_number: str,
        filename: str,
        content: bytes,
        generated_by_id: Optional[str] = None,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> GeneratedDocument:
        return await self.store_document(
            document_type="COMPLIANCE_REPORT",
            reference_number=reference_number,
            filename=filename,
            content_type="text/csv",
            content=content,
            related_entity_type="compliance",
            period_start=period_start,
            period_end=period_end,
            generated_by_id=generated_by_id,
        )

    async def generate_compliance_csv(self) -> bytes:
        transfer_service = TransferService(self.db)
        overview = await transfer_service.get_equipment_transfer_overview()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Item SKU",
            "Item Name",
            "Serial Number",
            "ID Number",
            "Location",
            "Can Transfer",
            "Blocked Reasons",
            "Requires Calibration",
            "Calibration Due At",
            "Calibration Result",
            "Calibration Due Soon",
            "Maintenance Last Completed At",
            "Maintenance Completed This Period",
        ])
        for row in overview.get("items", []):
            writer.writerow([ReportService._safe_spreadsheet_value(value) for value in [
                row.get("item_sku") or "",
                row.get("item_name") or "",
                row.get("serial_number") or "",
                row.get("id_number") or "",
                row.get("location_name") or row.get("location_id") or "",
                "Yes" if row.get("can_transfer") else "No",
                "; ".join(row.get("blocked_reasons") or []),
                "Yes" if row.get("requires_calibration") else "No",
                self._format_csv_datetime(row.get("calibration_due_at")),
                row.get("calibration_result") or "",
                "Yes" if row.get("calibration_due_soon") else "No",
                self._format_csv_datetime(row.get("maintenance_last_completed_at")),
                "Yes" if row.get("maintenance_completed_this_period") else "No",
            ]])
        return output.getvalue().encode("utf-8-sig")

    async def generate_monthly_documents(
        self,
        *,
        year: int,
        month: int,
        generated_by_id: Optional[str] = None,
    ) -> List[GeneratedDocument]:
        start, end = self.month_bounds(year, month)

        indent_result = await self.db.execute(
            select(PurchaseIndent)
            .where(PurchaseIndent.indent_date >= start, PurchaseIndent.indent_date <= end)
            .order_by(PurchaseIndent.indent_date)
        )
        for indent in indent_result.scalars().all():
            await self.generate_and_store_pi_pdf(
                indent.id,
                generated_by_id=generated_by_id,
                period_start=start,
                period_end=end,
            )

        transfer_result = await self.db.execute(
            select(Transfer)
            .where(
                Transfer.created_at >= start,
                Transfer.created_at <= end,
                Transfer.status.in_([
                    TransferStatus.APPROVED,
                    TransferStatus.IN_TRANSIT,
                    TransferStatus.RECEIVED,
                    TransferStatus.PARTIALLY_RECEIVED,
                ]),
            )
            .order_by(Transfer.created_at)
        )
        for transfer in transfer_result.scalars().all():
            await self.generate_and_store_dc_pdf(
                transfer.id,
                generated_by_id=generated_by_id,
                period_start=start,
                period_end=end,
            )

        report_service = ReportService(self.db)
        purchase_io, purchase_filename, _ = await report_service.export_purchase_register(
            start_date=start.date(),
            end_date=end.date(),
        )
        await self.store_register_xlsx(
            document_type="PURCHASE_REGISTER",
            reference_number=f"PURCHASE_REGISTER_{year}_{month:02d}",
            filename=f"purchase_register_{year}_{month:02d}.xlsx",
            content=purchase_io.getvalue(),
            generated_by_id=generated_by_id,
            period_start=start,
            period_end=end,
        )

        stock_io, _, _ = await report_service.export_inventory_report(
            format="xlsx",
            start_date=start.date(),
            end_date=end.date(),
        )
        await self.store_register_xlsx(
            document_type="STOCK_REGISTER",
            reference_number=f"STOCK_REGISTER_{year}_{month:02d}",
            filename=f"stock_register_{year}_{month:02d}.xlsx",
            content=stock_io.getvalue(),
            generated_by_id=generated_by_id,
            period_start=start,
            period_end=end,
        )

        compliance_csv = await self.generate_compliance_csv()
        await self.store_compliance_csv(
            reference_number=f"COMPLIANCE_REPORT_{year}_{month:02d}",
            filename=f"compliance_report_{year}_{month:02d}.csv",
            content=compliance_csv,
            generated_by_id=generated_by_id,
            period_start=start,
            period_end=end,
        )

        return await self._documents_for_period(start, end)

    async def send_monthly_zip_to_admins(
        self,
        *,
        year: int,
        month: int,
        generated_by_id: Optional[str] = None,
    ) -> dict:
        start, end = self.month_bounds(year, month)
        docs = await self.generate_monthly_documents(
            year=year,
            month=month,
            generated_by_id=generated_by_id,
        )
        zip_parts = self._build_monthly_zip_parts(docs, year, month, start, end)
        recipients = await self._admin_emails()
        if not recipients:
            raise BadRequestError(message="No active admin email found for monthly document email")

        email_service = get_email_service()
        batch_id = f"monthly-docs-{year}-{month:02d}-{self._now().strftime('%Y%m%d%H%M%S')}"
        sent_files = []
        sent = True
        for filename, content in zip_parts:
            subject = filename.replace(".zip", "").replace("_", " ")
            body_text = (
                f"Attached are generated PI, DC, Purchase Register, Stock Register, and Compliance Report files "
                f"for {start.strftime('%B %Y')}.\n\n"
                f"Generated document copies expire after {settings.GENERATED_DOCUMENT_RETENTION_DAYS} days."
            )
            ok = email_service.send_email_with_attachments(
                to_emails=recipients,
                subject=subject,
                body_html=f"<p>{escape(body_text).replace(chr(10), '<br>')}</p>",
                body_text=body_text,
                attachments=[(filename, content, "application/zip")],
            )
            sent = sent and ok
            sent_files.append(filename)
            await self.store_document(
                document_type="MONTHLY_ZIP",
                reference_number=filename.replace(".zip", ""),
                filename=filename,
                content_type="application/zip",
                content=content,
                related_entity_type="monthly_bundle",
                period_start=start,
                period_end=end,
                generated_by_id=generated_by_id,
                email_batch_id=batch_id,
                expires_at=self._expiry(),
            )

        now = self._now()
        for doc in docs:
            doc.email_batch_id = batch_id
            doc.emailed_at = now
            doc.expires_at = self._expiry()
        await self.db.commit()

        return {
            "sent": sent,
            "recipients": recipients,
            "zip_files": sent_files,
            "document_count": len(docs),
            "batch_id": batch_id,
        }

    async def cleanup_expired(self) -> int:
        result = await self.db.execute(
            delete(GeneratedDocument).where(
                GeneratedDocument.expires_at.is_not(None),
                GeneratedDocument.expires_at <= self._now(),
            )
        )
        await self.db.commit()
        return int(result.rowcount or 0)

    async def _documents_for_period(self, start: datetime, end: datetime) -> List[GeneratedDocument]:
        result = await self.db.execute(
            select(GeneratedDocument)
            .where(
                or_(
                    and_(GeneratedDocument.generated_at >= start, GeneratedDocument.generated_at <= end),
                    and_(GeneratedDocument.period_start >= start, GeneratedDocument.period_start <= end),
                ),
                GeneratedDocument.document_type.in_(["PI", "DC", "PURCHASE_REGISTER", "STOCK_REGISTER", "COMPLIANCE_REPORT"]),
            )
            .order_by(GeneratedDocument.document_type, GeneratedDocument.generated_at)
        )
        return list(result.scalars().all())

    async def _admin_emails(self) -> List[str]:
        result = await self.db.execute(
            select(User.email).where(User.role == UserRole.ADMIN, User.is_active == True)
        )
        return [email for email in result.scalars().all() if email]

    def _build_monthly_zip_parts(
        self,
        docs: List[GeneratedDocument],
        year: int,
        month: int,
        start: datetime,
        end: datetime,
    ) -> List[Tuple[str, bytes]]:
        month_label = start.strftime("%B_%Y")
        full_name = f"Scientech_IMS_Documents_{month_label}.zip"
        full_zip = self._zip_docs(docs, f"{month_label}")
        max_bytes = settings.MONTHLY_DOCUMENT_ZIP_MAX_MB * 1024 * 1024
        if len(full_zip) <= max_bytes:
            return [(full_name, full_zip)]

        day_15 = datetime.combine(date(year, month, 15), time.max, tzinfo=timezone.utc)
        first_docs = [d for d in docs if self._doc_date(d) <= day_15]
        second_docs = [d for d in docs if self._doc_date(d) > day_15]
        parts = [
            (f"Scientech_IMS_Documents_{month_label}_01_to_15.zip", self._zip_docs(first_docs, f"{month_label}/01_to_15")),
            (
                f"Scientech_IMS_Documents_{month_label}_16_to_{end.day:02d}.zip",
                self._zip_docs(second_docs, f"{month_label}/16_to_{end.day:02d}"),
            ),
        ]
        if all(len(content) <= max_bytes for _, content in parts):
            return parts

        ranges = [(1, 7), (8, 15), (16, 23), (24, end.day)]
        weekly_parts = []
        for start_day, end_day in ranges:
            p_start = datetime.combine(date(year, month, start_day), time.min, tzinfo=timezone.utc)
            p_end = datetime.combine(date(year, month, end_day), time.max, tzinfo=timezone.utc)
            p_docs = [d for d in docs if p_start <= self._doc_date(d) <= p_end]
            if not p_docs:
                continue
            weekly_parts.append((
                f"Scientech_IMS_Documents_{month_label}_{start_day:02d}_to_{end_day:02d}.zip",
                self._zip_docs(p_docs, f"{month_label}/{start_day:02d}_to_{end_day:02d}"),
            ))
        return weekly_parts

    def _zip_docs(self, docs: Iterable[GeneratedDocument], root: str) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for doc in docs:
                folder = {
                "PI": "PI",
                "DC": "DC",
                "PURCHASE_REGISTER": "Registers",
                "STOCK_REGISTER": "Registers",
                "COMPLIANCE_REPORT": "Compliance",
            }.get(doc.document_type, doc.document_type)
            zf.writestr(f"{root}/{folder}/{doc.filename}", doc.content)
        return output.getvalue()

    def _format_csv_datetime(self, value) -> str:
        if not value:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        return str(value)

    def _doc_date(self, doc: GeneratedDocument) -> datetime:
        value = doc.period_start or doc.generated_at
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def month_bounds(self, year: int, month: int) -> Tuple[datetime, datetime]:
        last_day = monthrange(year, month)[1]
        start = datetime.combine(date(year, month, 1), time.min, tzinfo=timezone.utc)
        end = datetime.combine(date(year, month, last_day), time.max, tzinfo=timezone.utc)
        return start, end

    def _safe_filename(self, value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)

    def _html_to_document(self, html: str, base_filename: str) -> Tuple[bytes, str, str]:
        if settings.GENERATED_DOCUMENT_PREFER_PDF:
            try:
                from weasyprint import HTML

                return HTML(string=html).write_pdf(), f"{base_filename}.pdf", "application/pdf"
            except Exception:
                pass
        return html.encode("utf-8"), f"{base_filename}.html", "text/html; charset=utf-8"

    def _build_pi_html(self, indent) -> str:
        rows = "".join(
            f"<tr><td>{idx}</td><td>{escape(line.item_name or line.item_sku or line.item_id)}</td>"
            f"<td>{line.quantity_requested}</td><td>{indent.indent_date:%d-%m-%Y}</td>"
            f"<td>{escape(indent.supplying_location_name or '')}</td></tr>"
            for idx, line in enumerate(indent.items, 1)
        )
        return f"""<!doctype html><html><head><meta charset="utf-8">
<style>body{{font-family:Arial,sans-serif;color:#000}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #000;padding:6px}}h1,h2{{text-align:center;margin:4px}}</style>
</head><body>
<h1>Scientech Services</h1><h2>Purchase Indent</h2>
<p><strong>PI No:</strong> {escape(indent.indent_number)} &nbsp; <strong>Date:</strong> {indent.indent_date:%d-%m-%Y}</p>
<p><strong>From:</strong> {escape(indent.requesting_location_name or '')} &nbsp; <strong>To:</strong> {escape(indent.supplying_location_name or '')}</p>
<table><thead><tr><th>No.</th><th>Raw Material & Specification</th><th>Qty Required</th><th>Reqd By Date</th><th>To be Sent To</th></tr></thead><tbody>{rows}</tbody></table>
<p style="text-align:right;margin-top:48px;"><strong>FOR SCIENTECH SERVICES</strong><br><br>Office Assistant</p>
</body></html>"""

    def _build_dc_html(
        self,
        transfer,
        dc_number: str,
        company_name: str = "M/s Scientech Services",
        logo_data_url: Optional[str] = None,
    ) -> str:
        remarks = (
            transfer.shipping_notes
            or transfer.approval_notes
            or transfer.request_notes
            or ""
        )
        def location_address(location) -> str:
            if not location:
                return ""
            return ", ".join(
                str(part).strip()
                for part in (
                    location.address,
                    location.city,
                    location.state,
                    location.postal_code,
                    location.country,
                )
                if part and str(part).strip()
            )
        logo = (
            f'<img src="{escape(logo_data_url)}" alt="Scientech Services logo" '
            'style="max-width:70px;max-height:55px">'
            if logo_data_url
            else '<div style="display:inline-block;border:3px solid #1769aa;border-radius:8px;'
            'padding:8px 10px;color:#1769aa;font-size:22px;font-weight:bold">SS</div>'
        )
        rows = "".join(
            f"<tr><td>{idx}</td><td>{escape(line.item_name or line.item_sku or line.item_id)}</td>"
            f"<td>{line.quantity_shipped or line.quantity_requested}</td><td>{escape(line.notes or '')}</td></tr>"
            for idx, line in enumerate(transfer.items, 1)
        )
        dc_date = (transfer.shipped_at or transfer.updated_at or transfer.created_at).strftime("%d-%m-%Y")
        return f"""<!doctype html><html><head><meta charset="utf-8">
<style>body{{font-family:Arial,sans-serif;color:#000}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #000;padding:6px}}h1,h2{{text-align:center;margin:4px}}</style>
</head><body>
<div style="display:flex;align-items:center;justify-content:center;gap:18px">{logo}<div><h1>{escape(company_name)}</h1><h2>Delivery Challan</h2></div></div>
<p><strong>DC No:</strong> {escape(dc_number)} &nbsp; <strong>Date:</strong> {dc_date}</p>
<p><strong>To:</strong> {escape(transfer.to_location_name or transfer.to_location_id)}<br><strong>Address:</strong> {escape(location_address(transfer.to_location))}</p>
<p><strong>From:</strong> {escape(transfer.from_location_name or transfer.from_location_id)}<br><strong>Address:</strong> {escape(location_address(transfer.from_location))}</p>
<h3 style="text-align:center;">RETURNABLE/NON RETURNABLE</h3>
<table><thead><tr><th>Sl No</th><th>Description</th><th>Quantity</th><th>Remarks</th></tr></thead><tbody>{rows}</tbody></table>
<p><strong>Remarks:</strong> {escape(remarks)}</p>
<p style="display:flex;justify-content:space-between;margin-top:48px;"><strong>Issued by,</strong><strong>Receiver's Signature</strong></p>
</body></html>"""
