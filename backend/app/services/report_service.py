"""
Report Service

Handles report generation and export.
"""

import csv
import io
import base64
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple, Any

from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.stock import Stock, StockLot
from app.models.item import Item
from app.models.location import Location
from app.models.category import Category
from app.models.transaction import Transaction, TransactionType
from app.models.asset import SerializedAsset
from app.models.branding import AppBranding
from app.models.calibration import CalibrationRecord
from app.core.exceptions import BadRequestError
from app.schemas.reports import (
    ReportFormat,
    InventoryReport,
    InventoryReportItem,
    TransactionReport,
    TransactionReportItem,
    CalibrationReport,
    CalibrationReportItem,
    StockMovementReport,
    StockMovementItem,
    AssetReport,
    AssetReportItem,
)


class ReportService:
    """Service for report generation."""
    
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _safe_spreadsheet_value(value: Any) -> Any:
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value

    @staticmethod
    def _date_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
        if end_date < start_date:
            raise BadRequestError(message="End date cannot be before start date")
        return (
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
        )

    async def _get_branding(self) -> Optional[AppBranding]:
        result = await self.db.execute(select(AppBranding).where(AppBranding.id == "default"))
        return result.scalar_one_or_none()
    
    async def generate_inventory_report(
        self,
        location_id: Optional[str] = None,
        category_id: Optional[str] = None,
        include_zero_stock: bool = False,
        location_ids: Optional[List[str]] = None,
    ) -> InventoryReport:
        """Generate inventory report."""
        query = (
            select(
                Item.sku,
                Item.name,
                Item.unit_of_measure,
                Item.standard_cost,
                Stock.reorder_point,
                Category.name.label("category_name"),
                Location.name.label("location_name"),
                Location.code.label("location_code"),
                Stock.quantity_on_hand,
            )
            .join(Stock, Stock.item_id == Item.id)
            .join(Location, Location.id == Stock.location_id)
            .outerjoin(Category, Category.id == Item.category_id)
            .where(Item.is_active == True)
        )
        
        if not include_zero_stock:
            query = query.where(Stock.quantity_on_hand > 0)
        
        if location_id:
            query = query.where(Stock.location_id == location_id)
        elif location_ids is not None:
            query = query.where(Stock.location_id.in_(location_ids))
        
        if category_id:
            query = query.where(Item.category_id == category_id)
        
        query = query.order_by(Item.sku)
        
        result = await self.db.execute(query)
        
        items = []
        total_quantity = Decimal("0")
        total_value = Decimal("0")
        
        for row in result.all():
            quantity = Decimal(str(row.quantity_on_hand or 0))
            unit_cost = Decimal(str(row.standard_cost or 0))
            item_value = quantity * unit_cost
            
            # Determine status
            status = "in_stock"
            if quantity <= 0:
                status = "out_of_stock"
            elif row.reorder_point and quantity <= row.reorder_point:
                status = "low_stock"
            
            items.append(
                InventoryReportItem(
                    sku=row.sku,
                    name=row.name,
                    category_name=row.category_name,
                    location_name=row.location_name,
                    location_code=row.location_code,
                    quantity=quantity,
                    unit_of_measure=row.unit_of_measure,
                    unit_cost=unit_cost if unit_cost else None,
                    total_value=item_value if item_value else None,
                    reorder_point=Decimal(str(row.reorder_point)) if row.reorder_point else None,
                    status=status,
                )
            )
            
            total_quantity += quantity
            total_value += item_value
        
        return InventoryReport(
            generated_at=datetime.utcnow(),
            generated_by="System",
            filters={
                "location_id": location_id,
                "category_id": category_id,
                "include_zero_stock": include_zero_stock,
            },
            summary={
                "total_items": len(items),
                "total_quantity": float(total_quantity),
                "total_value": float(total_value),
            },
            items=items,
        )
    
    async def export_inventory_report(
        self,
        format: ReportFormat,
        location_id: Optional[str] = None,
        category_id: Optional[str] = None,
        include_zero_stock: bool = False,
        location_ids: Optional[List[str]] = None,
        transfers_only: bool = False,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Tuple[io.BytesIO, str, str]:
        """Export inventory report as CSV or Excel."""
        report = await self.generate_inventory_report(
            location_id=location_id,
            category_id=category_id,
            include_zero_stock=include_zero_stock,
            location_ids=location_ids,
        )
        
        if format == ReportFormat.CSV:
            return self._export_to_csv(
                headers=["SKU", "Name", "Category", "Location", "Quantity", "Unit", "Unit Cost", "Total Value", "Status"],
                rows=[
                    [
                        item.sku,
                        item.name,
                        item.category_name or "",
                        item.location_name,
                        str(item.quantity),
                        item.unit_of_measure,
                        str(item.unit_cost or ""),
                        str(item.total_value or ""),
                        item.status,
                    ]
                    for item in report.items
                ],
                filename=f"inventory_report_{datetime.utcnow().strftime('%Y%m%d')}.csv",
            )
        else:
            return await self._export_stock_register_xlsx(
                location_id=location_id,
                category_id=category_id,
                include_zero_stock=include_zero_stock,
                location_ids=location_ids,
                transfers_only=transfers_only,
                start_date=start_date,
                end_date=end_date,
            )
    
    def _export_to_csv(
        self,
        headers: List[str],
        rows: List[List[Any]],
        filename: str,
    ) -> Tuple[io.BytesIO, str, str]:
        """Export data to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([self._safe_spreadsheet_value(value) for value in headers])
        writer.writerows(
            [self._safe_spreadsheet_value(value) for value in row] for row in rows
        )
        
        content = io.BytesIO(output.getvalue().encode("utf-8"))
        content.seek(0)
        
        return content, filename, "text/csv"

    async def _export_stock_register_xlsx(
        self,
        location_id: Optional[str] = None,
        category_id: Optional[str] = None,
        include_zero_stock: bool = False,
        location_ids: Optional[List[str]] = None,
        transfers_only: bool = False,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Tuple[io.BytesIO, str, str]:
        """Export inventory in the STR-F-01 stock register workbook format."""
        if start_date and end_date:
            self._date_bounds(start_date, end_date)
        wb = Workbook()
        ws = wb.active
        ws.title = "Stock_register"

        today = date.today()
        branding = await self._get_branding()
        register_title = await self._stock_register_title(category_id, transfers_only)
        self._build_stock_register_header(ws, today, register_title, branding)

        query = (
            select(Transaction)
            .options(
                selectinload(Transaction.item).selectinload(Item.category).selectinload(Category.category_type),
                selectinload(Transaction.location),
                selectinload(Transaction.lot),
            )
            .join(Item, Item.id == Transaction.item_id)
            .where(Item.is_active == True)
            .order_by(Item.sku, Transaction.location_id, Transaction.transaction_date, Transaction.id)
        )

        if location_id:
            query = query.where(Transaction.location_id == location_id)
        elif location_ids is not None:
            query = query.where(Transaction.location_id.in_(location_ids))

        if category_id:
            query = query.where(Item.category_id == category_id)

        if transfers_only:
            query = query.where(
                Transaction.transaction_type.in_([
                    TransactionType.TRANSFER_OUT,
                    TransactionType.TRANSFER_IN,
                ])
            )

        if start_date:
            query = query.where(Transaction.transaction_date >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            query = query.where(
                Transaction.transaction_date < datetime.combine(
                    end_date + timedelta(days=1), datetime.min.time()
                )
            )

        result = await self.db.execute(query)
        transactions = list(result.scalars().unique().all())

        current_key = None
        section_start = 24
        current_row = section_start
        sl_no = 1
        wrote_section = False
        seen_lots = set()

        balances: dict[Tuple[str, str], int] = {}

        for txn in transactions:
            item = txn.item
            location = txn.location
            lot = txn.lot
            if not item or not location:
                continue

            category = item.category
            key = (item.id, location.id)
            if key != current_key:
                if wrote_section:
                    current_row = self._add_stock_register_section_spacer(ws, current_row)
                current_key = key
                sl_no = 1
                wrote_section = True
                balances[key] = 0
                current_row = self._add_stock_register_section(
                    ws=ws,
                    row=current_row,
                    label=self._stock_register_item_label(item, category),
                    opening_balance=0,
                )

            txn_type = txn.transaction_type
            is_outgoing = txn_type in {
                TransactionType.ISSUE,
                TransactionType.TRANSFER_OUT,
                TransactionType.SCRAP,
            }
            movement_qty = int(txn.quantity or 0)
            signed_qty = -movement_qty if is_outgoing else movement_qty
            balances[key] += signed_qty
            notes = txn.notes or ""
            supplier = ""
            if "Supplier:" in notes:
                supplier = notes.split("Supplier:", 1)[1].split(".", 1)[0].strip()
            description = self._stock_register_description(item, location)
            if txn_type == TransactionType.ADJUSTMENT:
                description = f"{description} - Adjustment"
            elif txn_type in {TransactionType.TRANSFER_IN, TransactionType.TRANSFER_OUT}:
                description = f"{description} - Transfer"

            current_row = self._add_stock_register_data_row(
                ws=ws,
                row=current_row,
                sl_no=sl_no,
                entry_date=txn.transaction_date.date() if not is_outgoing and txn.transaction_date else None,
                supplier=supplier if txn_type == TransactionType.RECEIPT else "",
                invoice_no=txn.reference_number or "",
                description=description,
                batch_no=(lot.lot_number or lot.supplier_lot) if lot else (item.model or ""),
                mfg_date=lot.manufacture_date if lot else None,
                qty=movement_qty,
                issued_date=txn.transaction_date.date() if is_outgoing and txn.transaction_date else None,
                dc_no=txn.reference_number or "",
                balance=balances[key],
            )
            sl_no += 1

        if not transactions:
            self._add_stock_register_section(ws, section_start, "NO STOCK MOVEMENTS", 0)

        ws.freeze_panes = "B7"
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        prefix = "transfer_stock_register" if transfers_only else "stock_register"
        filename = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
        return (
            output,
            filename,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    async def _stock_register_title(self, category_id: Optional[str], transfers_only: bool) -> str:
        if transfers_only:
            return "Stock Register - Transfers"
        if not category_id:
            return "Stock Register"

        result = await self.db.execute(select(Category).where(Category.id == category_id))
        category = result.scalar_one_or_none()
        return f"Stock Register - {category.name}" if category else "Stock Register"

    def _build_stock_register_header(
        self,
        ws,
        generated_on: date,
        title: str,
        branding: Optional[AppBranding] = None,
    ) -> None:
        widths = {
            "A": 15,
            "B": 10,
            "C": 14,
            "D": 16,
            "E": 18,
            "F": 24,
            "G": 18,
            "H": 14,
            "I": 10,
            "J": 14,
            "K": 14,
            "L": 16,
            "M": 16,
            "N": 12,
        }
        for col, width in widths.items():
            ws.column_dimensions[col].width = width

        for row in range(1, 24):
            ws.row_dimensions[row].height = 24
        ws.row_dimensions[2].height = 30
        ws.row_dimensions[3].height = 30
        ws.row_dimensions[4].height = 30
        ws.row_dimensions[23].height = 12

        ws.merge_cells("B2:C4")
        ws.merge_cells("D2:M2")
        ws.merge_cells("D3:M4")
        ws.merge_cells("L5:M5")
        ws.merge_cells("N5:N6")

        if branding and branding.logo_data_url:
            self._add_excel_logo(ws, branding.logo_data_url, "B2")
        else:
            logo = ws["B2"]
            logo.value = "SS"
            logo.font = Font(name="Times New Roman", size=34, bold=True, color="C00000")
            logo.alignment = Alignment(horizontal="center", vertical="center")

        ws["D2"] = branding.company_name if branding else "M/s. Scientech Services"
        ws["D2"].font = Font(name="Times New Roman", size=18, bold=True)
        ws["D2"].alignment = Alignment(horizontal="center", vertical="center")

        ws["D3"] = title
        ws["D3"].font = Font(name="Times New Roman", size=18, bold=True)
        ws["D3"].alignment = Alignment(horizontal="center", vertical="center")

        ws["N2"] = "STR-F-01"
        ws["N3"] = "Rev 01"
        ws["N4"] = generated_on.strftime("%d-%b-%Y")

        headers = {
            "B5": "SL NO",
            "C5": "DATE",
            "D5": "Rcvd Client",
            "E5": "Invoice No",
            "F5": "Description",
            "G5": "Batch No",
            "H5": "MFG Date",
            "I5": "Qty",
            "J5": "Issued",
            "K5": "DC",
            "L5": "Issed Details",
            "N5": "Bal",
            "J6": "Date",
            "K6": "No",
            "L6": "Other Site",
            "M6": "BLR Site",
        }
        for cell, value in headers.items():
            ws[cell] = value

        thin = Side(style="thin", color="000000")
        medium = Side(style="medium", color="000000")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        header_border = Border(left=thin, right=thin, top=medium, bottom=medium)
        thick_bottom = Border(left=thin, right=thin, top=thin, bottom=medium)

        for row in ws.iter_rows(min_row=2, max_row=6, min_col=2, max_col=14):
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for row in ws.iter_rows(min_row=5, max_row=6, min_col=2, max_col=14):
            for cell in row:
                cell.font = Font(bold=True)
                cell.border = header_border if row[0].row == 5 else thick_bottom

        for col in range(2, 15):
            ws.cell(row=23, column=col).border = Border(top=medium)

    def _add_stock_register_section(self, ws, row: int, label: str, opening_balance: int) -> int:
        yellow = PatternFill("solid", fgColor="FFFF00")
        thin = Side(style="thin", color="000000")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=1).fill = yellow
        ws.cell(row=row, column=1).font = Font(bold=True, color="FF0000")
        ws.cell(row=row, column=1).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=6)
        ws.cell(row=row, column=4, value="Opening Bal")
        ws.cell(row=row, column=4).font = Font(size=14, bold=True)
        ws.cell(row=row, column=4).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=row, column=14, value=opening_balance)

        for col in range(2, 15):
            ws.cell(row=row, column=col).border = border
            ws.cell(row=row, column=col).alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[row].height = 28
        return row + 1

    def _add_stock_register_data_row(
        self,
        ws,
        row: int,
        sl_no: int,
        entry_date: Optional[date],
        supplier: str,
        invoice_no: str,
        description: str,
        batch_no: str,
        mfg_date: Optional[date],
        qty: int,
        issued_date: Optional[date],
        dc_no: str,
        balance: int,
    ) -> int:
        values = [
            sl_no,
            entry_date.strftime("%d-%b-%Y") if entry_date else "",
            supplier,
            invoice_no,
            description,
            batch_no,
            mfg_date.strftime("%d-%b-%Y") if mfg_date else "",
            qty,
            issued_date.strftime("%d-%b-%Y") if issued_date else "",
            dc_no,
            "",
            "",
            balance,
        ]
        thin = Side(style="thin", color="000000")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        for index, value in enumerate(values, start=2):
            cell = ws.cell(row=row, column=index, value=self._safe_spreadsheet_value(value))
            cell.border = border
            cell.alignment = Alignment(
                horizontal="center" if index not in (4, 5, 6) else "left",
                vertical="center",
                wrap_text=True,
            )
        ws.row_dimensions[row].height = 24
        return row + 1

    def _add_stock_register_section_spacer(self, ws, row: int) -> int:
        medium = Side(style="medium", color="000000")
        border = Border(top=medium)
        for col in range(2, 15):
            ws.cell(row=row, column=col).border = border
        ws.row_dimensions[row].height = 16
        return row + 1

    def _stock_register_item_label(self, item: Item, category: Optional[Category]) -> str:
        label_parts = [item.id_number or item.sku]
        if item.model:
            label_parts.append(item.model)
        elif category and category.name:
            label_parts.append(category.name)
        return "\n".join(part for part in label_parts if part)

    def _stock_register_description(self, item: Item, location: Location) -> str:
        details = [item.name]
        if item.manufacturer:
            details.append(item.manufacturer)
        if location.name:
            details.append(location.name)
        return " - ".join(details)

    async def export_purchase_register(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        location_id: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[io.BytesIO, str, str]:
        """Export purchase entries in the PUR-F-07 purchase register format."""
        if start_date and end_date:
            self._date_bounds(start_date, end_date)
        wb = Workbook()
        ws = wb.active
        ws.title = "Purchase Register"
        branding = await self._get_branding()
        self._build_purchase_register_header(ws, branding)

        receipt_query = (
            select(Transaction, Item, Category, StockLot)
            .join(Item, Item.id == Transaction.item_id)
            .outerjoin(Category, Category.id == Item.category_id)
            .outerjoin(StockLot, StockLot.id == Transaction.lot_id)
            .where(Transaction.transaction_type == TransactionType.RECEIPT)
            .order_by(Transaction.transaction_date, Transaction.reference_number)
        )

        if start_date:
            receipt_query = receipt_query.where(Transaction.transaction_date >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            receipt_query = receipt_query.where(
                Transaction.transaction_date < datetime.combine(
                    end_date + timedelta(days=1), datetime.min.time()
                )
            )
        if location_id:
            receipt_query = receipt_query.where(Transaction.location_id == location_id)
        elif location_ids is not None:
            receipt_query = receipt_query.where(Transaction.location_id.in_(location_ids))

        rows: list[dict[str, Any]] = []
        receipt_result = await self.db.execute(receipt_query)
        for txn, item, category, lot in receipt_result.all():
            notes = txn.notes or ""
            rows.append({
                "sort_date": txn.transaction_date.date() if txn.transaction_date else date.min,
                "date": txn.transaction_date.strftime("%d-%b-%Y") if txn.transaction_date else "",
                "supplier": self._extract_note_value(notes, "Supplier") or (lot.supplier if lot else ""),
                "invoice_no": self._extract_note_value(notes, "Invoice number") or txn.reference_number or "",
                "description": item.name,
                "quantity": txn.quantity,
                "type": self._purchase_register_type(item, category),
                "remarks": self._purchase_register_remarks(notes),
            })

        asset_query = (
            select(SerializedAsset)
            .options(
                selectinload(SerializedAsset.item).selectinload(Item.category),
                selectinload(SerializedAsset.location),
            )
            .join(Item, Item.id == SerializedAsset.item_id)
            .where(Item.is_serialized == True)
            .order_by(SerializedAsset.acquired_at, SerializedAsset.serial_number)
        )
        if start_date:
            asset_query = asset_query.where(SerializedAsset.acquired_at >= start_date)
        if end_date:
            asset_query = asset_query.where(SerializedAsset.acquired_at <= end_date)
        if location_id:
            asset_query = asset_query.where(SerializedAsset.location_id == location_id)
        elif location_ids is not None:
            asset_query = asset_query.where(SerializedAsset.location_id.in_(location_ids))

        asset_result = await self.db.execute(asset_query)
        for asset in asset_result.scalars().unique().all():
            item = asset.item
            category = item.category if item else None
            description_parts = [
                item.name if item else "Serialized Asset",
                f"Serial: {asset.serial_number}" if asset.serial_number else "",
                f"ID: {item.id_number}" if item and item.id_number else "",
                f"Model: {item.model}" if item and item.model else "",
            ]
            remarks_parts = [
                f"Location: {asset.location.name}" if asset.location else "",
                f"PO: {asset.purchase_order}" if asset.purchase_order else "",
                f"Status: {asset.status.value if hasattr(asset.status, 'value') else asset.status}" if asset.status else "",
                asset.notes or "",
            ]
            rows.append({
                "sort_date": asset.acquired_at or date.min,
                "date": asset.acquired_at.strftime("%d-%b-%Y") if asset.acquired_at else "",
                "supplier": asset.supplier_name or (item.manufacturer if item else ""),
                "invoice_no": asset.invoice_number or asset.purchase_order or "",
                "description": " | ".join(part for part in description_parts if part),
                "quantity": 1,
                "type": self._purchase_register_type(item, category) if item else "",
                "remarks": "\n".join(part for part in remarks_parts if part),
            })

        current_row = 5
        rows.sort(key=lambda row: (row["sort_date"], row["description"]))
        for sl_no, row in enumerate(rows, start=1):
            row_values = [
                sl_no,
                row["date"],
                row["supplier"],
                row["invoice_no"],
                row["description"],
                row["quantity"],
                row["type"],
                row["remarks"],
            ]
            self._add_purchase_register_row(ws, current_row, row_values)
            current_row += 1

        minimum_rows = 14
        while current_row <= minimum_rows:
            self._add_purchase_register_row(ws, current_row, [""] * 8)
            current_row += 1

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        filename = f"purchase_register_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
        return (
            output,
            filename,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def _build_purchase_register_header(self, ws, branding: Optional[AppBranding] = None) -> None:
        widths = {
            "A": 10,
            "B": 14,
            "C": 36,
            "D": 24,
            "E": 34,
            "F": 13,
            "G": 14,
            "H": 16,
        }
        for col, width in widths.items():
            ws.column_dimensions[col].width = width

        for row in range(1, 15):
            ws.row_dimensions[row].height = 24
        ws.row_dimensions[1].height = 34
        ws.row_dimensions[2].height = 34
        ws.row_dimensions[3].height = 24

        ws.merge_cells("A1:B3")
        ws.merge_cells("C1:F1")
        ws.merge_cells("C2:F3")

        if branding and branding.logo_data_url:
            self._add_excel_logo(ws, branding.logo_data_url, "A1")
        else:
            ws["A1"] = "SS"
            ws["A1"].font = Font(name="Times New Roman", size=34, bold=True, color="C00000")
            ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

        ws["C1"] = branding.company_name if branding else "M/s. SCIENTECH SERVICES"
        ws["C1"].font = Font(size=11, bold=True)
        ws["C1"].alignment = Alignment(horizontal="center", vertical="center")

        ws["C2"] = "Purchase Register"
        ws["C2"].font = Font(size=12, bold=True)
        ws["C2"].alignment = Alignment(horizontal="center", vertical="center")

        ws["G1"] = "Doc. No."
        ws["H1"] = "PUR-F-07"
        ws["G2"] = "Rev. No."
        ws["H2"] = "00"
        ws["G3"] = "Date"
        ws["H3"] = "01-Oct-2021"

        headers = ["Sl No", "Date", "Supplier", "Invoice No", "Description", "Qty Received", "Type", "Remarks"]
        for col, header in enumerate(headers, start=1):
            ws.cell(row=4, column=col, value=header)

        thin = Side(style="thin", color="000000")
        medium = Side(style="medium", color="000000")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        header_border = Border(left=thin, right=thin, top=medium, bottom=medium)

        for row in ws.iter_rows(min_row=1, max_row=4, min_col=1, max_col=8):
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for row in range(1, 4):
            for col in (7, 8):
                ws.cell(row=row, column=col).font = Font(bold=True)
        for cell in ws[4]:
            cell.font = Font(bold=True)
            cell.border = header_border

    def _add_excel_logo(self, ws, logo_data_url: str, anchor: str) -> None:
        try:
            _, encoded = logo_data_url.split(",", 1)
            image_bytes = io.BytesIO(base64.b64decode(encoded))
            image = ExcelImage(image_bytes)
            image.width = 78
            image.height = 58
            ws.add_image(image, anchor)
        except Exception:
            ws[anchor] = "SS"
            ws[anchor].font = Font(name="Times New Roman", size=34, bold=True, color="C00000")
            ws[anchor].alignment = Alignment(horizontal="center", vertical="center")

    def _add_purchase_register_row(self, ws, row: int, values: List[Any]) -> None:
        thin = Side(style="thin", color="000000")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=self._safe_spreadsheet_value(value))
            cell.border = border
            cell.alignment = Alignment(
                horizontal="left" if col in (3, 4, 5, 8) else "center",
                vertical="center",
                wrap_text=True,
            )

    def _extract_note_value(self, notes: str, label: str) -> str:
        prefix = f"{label}:"
        for line in notes.splitlines():
            if line.lower().startswith(prefix.lower()):
                return line.split(":", 1)[1].strip()
        return ""

    def _purchase_register_remarks(self, notes: str) -> str:
        hidden_prefixes = ("supplier:", "invoice number:")
        remarks = [
            line.strip()
            for line in notes.splitlines()
            if line.strip() and not line.strip().lower().startswith(hidden_prefixes)
        ]
        return "\n".join(remarks)

    def _purchase_register_type(self, item: Item, category: Optional[Category]) -> str:
        key = (item.asset_type or item.category_type_key or "").lower()
        labels = {
            "equipment": "Equipment",
            "instrument": "Instrument",
            "consumable": "Consumable",
            "accessory": "Accessory",
        }
        if key in labels:
            return labels[key]
        if category and category.name:
            return category.name
        return item.asset_type or ""
    
    async def generate_transaction_report(
        self,
        start_date: date,
        end_date: date,
        location_id: Optional[str] = None,
        transaction_type: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> TransactionReport:
        """Generate transaction report for date range."""
        start_datetime, end_datetime = self._date_bounds(start_date, end_date)
        
        query = (
            select(
                Transaction.reference_number,
                Transaction.transaction_type,
                Transaction.quantity,
                Transaction.unit_cost,
                Transaction.total_cost,
                Transaction.transaction_date,
                Transaction.notes,
                Item.sku.label("item_sku"),
                Item.name.label("item_name"),
                Location.name.label("location_name"),
            )
            .join(Item, Item.id == Transaction.item_id)
            .join(Location, Location.id == Transaction.location_id)
            .where(
                and_(
                    Transaction.transaction_date >= start_datetime,
                    Transaction.transaction_date < end_datetime,
                )
            )
        )
        
        if location_id:
            query = query.where(Transaction.location_id == location_id)
        elif location_ids is not None:
            query = query.where(Transaction.location_id.in_(location_ids))
        
        if transaction_type:
            query = query.where(Transaction.transaction_type == transaction_type)
        
        query = query.order_by(Transaction.transaction_date.desc())
        
        result = await self.db.execute(query)
        
        transactions = []
        total_value = Decimal("0")
        
        for row in result.all():
            transactions.append(
                TransactionReportItem(
                    reference_number=row.reference_number,
                    transaction_type=row.transaction_type,
                    item_sku=row.item_sku,
                    item_name=row.item_name,
                    quantity=Decimal(str(row.quantity)),
                    unit_cost=Decimal(str(row.unit_cost)) if row.unit_cost else None,
                    total_cost=Decimal(str(row.total_cost)) if row.total_cost else None,
                    location_name=row.location_name,
                    performed_by="System",
                    created_at=row.transaction_date,
                    notes=row.notes,
                )
            )
            if row.total_cost:
                total_value += Decimal(str(row.total_cost))
        
        return TransactionReport(
            generated_at=datetime.utcnow(),
            generated_by="System",
            date_range={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            filters={
                "location_id": location_id,
                "transaction_type": transaction_type,
            },
            summary={
                "total_transactions": len(transactions),
                "total_value": float(total_value),
            },
            transactions=transactions,
        )
    
    async def export_transaction_report(
        self,
        format: ReportFormat,
        start_date: date,
        end_date: date,
        location_id: Optional[str] = None,
        transaction_type: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[io.BytesIO, str, str]:
        """Export transaction report."""
        report = await self.generate_transaction_report(
            start_date=start_date,
            end_date=end_date,
            location_id=location_id,
            transaction_type=transaction_type,
            location_ids=location_ids,
        )
        
        return self._export_to_csv(
            headers=["Reference", "Type", "SKU", "Item", "Quantity", "Unit Cost", "Total", "Location", "Date"],
            rows=[
                [
                    txn.reference_number,
                    txn.transaction_type,
                    txn.item_sku,
                    txn.item_name,
                    str(txn.quantity),
                    str(txn.unit_cost or ""),
                    str(txn.total_cost or ""),
                    txn.location_name,
                    txn.created_at.isoformat(),
                ]
                for txn in report.transactions
            ],
            filename=f"transaction_report_{start_date}_{end_date}.csv",
        )
    
    async def generate_calibration_report(
        self,
        location_id: Optional[str] = None,
        status: Optional[str] = None,
        days_until_due: int = 30,
        location_ids: Optional[List[str]] = None,
    ) -> CalibrationReport:
        """Generate calibration status report."""
        # Simplified implementation
        return CalibrationReport(
            generated_at=datetime.utcnow(),
            generated_by="System",
            filters={
                "location_id": location_id,
                "status": status,
                "days_until_due": days_until_due,
            },
            summary={
                "total_records": 0,
                "due_soon": 0,
                "expired": 0,
            },
            records=[],
        )
    
    async def export_calibration_report(
        self,
        format: ReportFormat,
        location_id: Optional[str] = None,
        status: Optional[str] = None,
        days_until_due: int = 30,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[io.BytesIO, str, str]:
        """Export calibration report."""
        report = await self.generate_calibration_report(
            location_id=location_id,
            status=status,
            days_until_due=days_until_due,
            location_ids=location_ids,
        )
        
        return self._export_to_csv(
            headers=["Serial Number", "Asset Name", "Location", "Status", "Last Calibration", "Due Date", "Days Until Due"],
            rows=[
                [
                    rec.serial_number,
                    rec.asset_name,
                    rec.location_name,
                    rec.status,
                    str(rec.last_calibration_date or ""),
                    str(rec.due_date),
                    str(rec.days_until_due),
                ]
                for rec in report.records
            ],
            filename=f"calibration_report_{datetime.utcnow().strftime('%Y%m%d')}.csv",
        )
    
    async def generate_stock_movement_report(
        self,
        start_date: date,
        end_date: date,
        location_id: Optional[str] = None,
        item_id: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> StockMovementReport:
        """Generate stock movement analysis report."""
        start_datetime, end_datetime = self._date_bounds(start_date, end_date)
        query = (
            select(Transaction, Item, Location)
            .join(Item, Item.id == Transaction.item_id)
            .join(Location, Location.id == Transaction.location_id)
            .where(
                Item.is_active == True,
                Transaction.transaction_date < end_datetime,
            )
            .order_by(Item.name, Location.name, Transaction.transaction_date, Transaction.id)
        )
        if location_id:
            query = query.where(Transaction.location_id == location_id)
        elif location_ids is not None:
            query = query.where(Transaction.location_id.in_(location_ids))
        if item_id:
            query = query.where(Transaction.item_id == item_id)

        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for txn, item, location in (await self.db.execute(query)).all():
            key = (txn.item_id, txn.location_id)
            bucket = buckets.setdefault(key, {
                "item": item, "location": location, "opening": Decimal("0"),
                "receipt": Decimal("0"), "issue": Decimal("0"),
                "return": Decimal("0"), "adjustment": Decimal("0"),
                "transfer_in": Decimal("0"), "transfer_out": Decimal("0"),
            })
            quantity = Decimal(str(txn.quantity or 0))
            kind = txn.transaction_type.value if hasattr(txn.transaction_type, "value") else str(txn.transaction_type)
            delta = (
                abs(quantity) if kind in {"receipt", "return", "transfer_in"}
                else -abs(quantity) if kind in {"issue", "transfer_out", "scrap"}
                else quantity
            )
            transaction_date = txn.transaction_date.replace(tzinfo=None)
            if transaction_date < start_datetime:
                bucket["opening"] += delta
            elif kind in bucket:
                bucket[kind] += abs(quantity)
            else:
                bucket["adjustment"] += delta

        movements: list[StockMovementItem] = []
        total_movement = Decimal("0")
        for bucket in buckets.values():
            period_delta = (
                bucket["receipt"] + bucket["return"] + bucket["transfer_in"]
                - bucket["issue"] - bucket["transfer_out"] + bucket["adjustment"]
            )
            total_movement += sum(
                abs(bucket[name]) for name in (
                    "receipt", "issue", "return", "adjustment", "transfer_in", "transfer_out"
                )
            )
            movements.append(StockMovementItem(
                item_sku=bucket["item"].sku,
                item_name=bucket["item"].name,
                location_name=bucket["location"].name,
                opening_balance=bucket["opening"],
                receipts=bucket["receipt"], issues=bucket["issue"],
                returns=bucket["return"], adjustments=bucket["adjustment"],
                transfers_in=bucket["transfer_in"], transfers_out=bucket["transfer_out"],
                closing_balance=bucket["opening"] + period_delta,
            ))

        return StockMovementReport(
            generated_at=datetime.utcnow(),
            generated_by="System",
            date_range={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            filters={
                "location_id": location_id,
                "item_id": item_id,
            },
            summary={
                "total_items": len(movements),
                "total_movement": float(total_movement),
            },
            movements=movements,
        )
    
    async def generate_asset_report(
        self,
        location_id: Optional[str] = None,
        status: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> AssetReport:
        """Generate asset report."""
        query = (
            select(SerializedAsset)
            .options(
                selectinload(SerializedAsset.item),
                selectinload(SerializedAsset.location),
                selectinload(SerializedAsset.assigned_to),
            )
        )
        
        if location_id:
            query = query.where(SerializedAsset.location_id == location_id)
        elif location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        if status:
            query = query.where(SerializedAsset.status == status)
        
        query = query.order_by(SerializedAsset.serial_number)
        
        result = await self.db.execute(query)
        
        assets = []
        for asset in result.scalars().unique().all():
            assets.append(
                AssetReportItem(
                    serial_number=asset.serial_number,
                    name=asset.item.name if asset.item else "",
                    item_sku=asset.item.sku if asset.item else None,
                    location_name=asset.location.name if asset.location else "",
                    status=asset.status,
                    assigned_to=asset.assigned_to.name if asset.assigned_to else None,
                    purchase_date=asset.acquired_at,
                    purchase_price=Decimal(str(asset.cost)) if asset.cost else None,
                    warranty_expiry=asset.warranty_expiry,
                    last_calibration=None,
                    next_calibration_due=None,
                    last_maintenance=None,
                )
            )
        
        return AssetReport(
            generated_at=datetime.utcnow(),
            generated_by="System",
            filters={
                "location_id": location_id,
                "status": status,
            },
            summary={
                "total_assets": len(assets),
                "in_service_count": sum(1 for a in assets if a.status == "in_service"),
                "under_maintenance_count": sum(1 for a in assets if a.status == "under_maintenance"),
                "under_calibration_count": sum(1 for a in assets if a.status == "under_calibration"),
            },
            assets=assets,
        )
    
    async def export_asset_report(
        self,
        format: ReportFormat,
        location_id: Optional[str] = None,
        status: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[io.BytesIO, str, str]:
        """Export asset report."""
        report = await self.generate_asset_report(
            location_id=location_id,
            status=status,
            location_ids=location_ids,
        )
        
        return self._export_to_csv(
            headers=["Serial Number", "Name", "SKU", "Location", "Status", "Assigned To", "Purchase Date", "Purchase Price"],
            rows=[
                [
                    asset.serial_number,
                    asset.name,
                    asset.item_sku or "",
                    asset.location_name,
                    asset.status,
                    asset.assigned_to or "",
                    str(asset.purchase_date or ""),
                    str(asset.purchase_price or ""),
                ]
                for asset in report.assets
            ],
            filename=f"asset_report_{datetime.utcnow().strftime('%Y%m%d')}.csv",
        )
