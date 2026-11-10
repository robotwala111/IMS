"""
Reports Endpoints

Report generation for inventory analytics.
"""

from datetime import date, datetime, time, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    require_manager_or_admin,
    require_location_access,
)
from app.core.logging import get_logger
from app.schemas.reports import (
    InventoryReport,
    TransactionReport,
    CalibrationReport,
    StockMovementReport,
    AssetReport,
    ReportFormat,
)
from app.services.report_service import ReportService
from app.services.generated_document_service import GeneratedDocumentService

logger = get_logger(__name__)
router = APIRouter()


@router.get("/inventory", response_model=InventoryReport)
async def get_inventory_report(
    current_user: CurrentUser,
    db: DB,
    location_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    include_zero_stock: bool = Query(False),
    _: None = Depends(require_manager_or_admin),
) -> InventoryReport:
    """
    Generate inventory report (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    return await report_service.generate_inventory_report(
        location_id=location_id,
        category_id=category_id,
        include_zero_stock=include_zero_stock,
        location_ids=location_ids,
    )


@router.get("/inventory/export")
async def export_inventory_report(
    current_user: CurrentUser,
    db: DB,
    format: ReportFormat = Query(ReportFormat.CSV),
    location_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    include_zero_stock: bool = Query(False),
    transfers_only: bool = Query(False),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    _: None = Depends(require_manager_or_admin),
) -> StreamingResponse:
    """
    Export inventory report as CSV or Excel (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    content, filename, content_type = await report_service.export_inventory_report(
        format=format,
        location_id=location_id,
        category_id=category_id,
        include_zero_stock=include_zero_stock,
        location_ids=location_ids,
        transfers_only=transfers_only,
        start_date=start_date,
        end_date=end_date,
    )

    if format == ReportFormat.EXCEL:
        doc_service = GeneratedDocumentService(db)
        period_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc) if start_date else None
        period_end = datetime.combine(end_date, time.max, tzinfo=timezone.utc) if end_date else None
        await doc_service.store_register_xlsx(
            document_type="STOCK_REGISTER",
            reference_number=f"STOCK_REGISTER_{date.today().isoformat()}",
            filename=filename,
            content=content.getvalue(),
            generated_by_id=current_user.id,
            period_start=period_start,
            period_end=period_end,
        )
        content.seek(0)
    
    return StreamingResponse(
        content,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/transactions", response_model=TransactionReport)
async def get_transaction_report(
    current_user: CurrentUser,
    db: DB,
    start_date: date = Query(...),
    end_date: date = Query(...),
    location_id: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    _: None = Depends(require_manager_or_admin),
) -> TransactionReport:
    """
    Generate transaction report for date range (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    return await report_service.generate_transaction_report(
        start_date=start_date,
        end_date=end_date,
        location_id=location_id,
        transaction_type=transaction_type,
        location_ids=location_ids,
    )


@router.get("/transactions/export")
async def export_transaction_report(
    current_user: CurrentUser,
    db: DB,
    start_date: date = Query(...),
    end_date: date = Query(...),
    format: ReportFormat = Query(ReportFormat.CSV),
    location_id: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    _: None = Depends(require_manager_or_admin),
) -> StreamingResponse:
    """
    Export transaction report as CSV or Excel (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    content, filename, content_type = await report_service.export_transaction_report(
        format=format,
        start_date=start_date,
        end_date=end_date,
        location_id=location_id,
        transaction_type=transaction_type,
        location_ids=location_ids,
    )
    
    return StreamingResponse(
        content,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/purchase-register/export")
async def export_purchase_register(
    current_user: CurrentUser,
    db: DB,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    location_id: Optional[str] = Query(None),
    _: None = Depends(require_manager_or_admin),
) -> StreamingResponse:
    """
    Export purchase receipt transactions in PUR-F-07 Excel format.
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)

    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]

    content, filename, content_type = await report_service.export_purchase_register(
        start_date=start_date,
        end_date=end_date,
        location_id=location_id,
        location_ids=location_ids,
    )

    doc_service = GeneratedDocumentService(db)
    period_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc) if start_date else None
    period_end = datetime.combine(end_date, time.max, tzinfo=timezone.utc) if end_date else None
    await doc_service.store_register_xlsx(
        document_type="PURCHASE_REGISTER",
        reference_number=f"PURCHASE_REGISTER_{date.today().isoformat()}",
        filename=filename,
        content=content.getvalue(),
        generated_by_id=current_user.id,
        period_start=period_start,
        period_end=period_end,
    )
    content.seek(0)

    return StreamingResponse(
        content,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/calibration", response_model=CalibrationReport)
async def get_calibration_report(
    current_user: CurrentUser,
    db: DB,
    location_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="due_soon, expired, or all"),
    days_until_due: int = Query(30, ge=1, le=365),
    _: None = Depends(require_manager_or_admin),
) -> CalibrationReport:
    """
    Generate calibration status report (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    return await report_service.generate_calibration_report(
        location_id=location_id,
        status=status,
        days_until_due=days_until_due,
        location_ids=location_ids,
    )


@router.get("/calibration/export")
async def export_calibration_report(
    current_user: CurrentUser,
    db: DB,
    format: ReportFormat = Query(ReportFormat.CSV),
    location_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    days_until_due: int = Query(30, ge=1, le=365),
    _: None = Depends(require_manager_or_admin),
) -> StreamingResponse:
    """
    Export calibration report as CSV or Excel (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    content, filename, content_type = await report_service.export_calibration_report(
        format=format,
        location_id=location_id,
        status=status,
        days_until_due=days_until_due,
        location_ids=location_ids,
    )
    
    return StreamingResponse(
        content,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/stock-movement", response_model=StockMovementReport)
async def get_stock_movement_report(
    current_user: CurrentUser,
    db: DB,
    start_date: date = Query(...),
    end_date: date = Query(...),
    location_id: Optional[str] = Query(None),
    item_id: Optional[str] = Query(None),
    _: None = Depends(require_manager_or_admin),
) -> StockMovementReport:
    """
    Generate stock movement analysis report (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    return await report_service.generate_stock_movement_report(
        start_date=start_date,
        end_date=end_date,
        location_id=location_id,
        item_id=item_id,
        location_ids=location_ids,
    )


@router.get("/assets", response_model=AssetReport)
async def get_asset_report(
    current_user: CurrentUser,
    db: DB,
    location_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    _: None = Depends(require_manager_or_admin),
) -> AssetReport:
    """
    Generate serialized asset report (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    return await report_service.generate_asset_report(
        location_id=location_id,
        status=status,
        location_ids=location_ids,
    )


@router.get("/assets/export")
async def export_asset_report(
    current_user: CurrentUser,
    db: DB,
    format: ReportFormat = Query(ReportFormat.CSV),
    location_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    _: None = Depends(require_manager_or_admin),
) -> StreamingResponse:
    """
    Export asset report as CSV or Excel (Manager or Admin).
    """
    report_service = ReportService(db)
    if location_id:
        require_location_access(current_user, location_id)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    content, filename, content_type = await report_service.export_asset_report(
        format=format,
        location_id=location_id,
        status=status,
        location_ids=location_ids,
    )
    
    return StreamingResponse(
        content,
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
