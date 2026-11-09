"""Generated document endpoints."""

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from app.api.v1.dependencies import CurrentUser, DB, require_admin, require_admin_or_ho_manager
from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError
from app.schemas.generated_document import (
    CleanupGeneratedDocumentsResponse,
    GeneratedDocumentListResponse,
    MonthlyDocumentEmailResponse,
)
from app.services.generated_document_service import GeneratedDocumentService


router = APIRouter()


def _validate_cron_secret(
    secret: Optional[str] = None,
    authorization: Optional[str] = None,
    query_secret: Optional[str] = None,
) -> None:
    if not settings.GENERATED_DOCUMENT_CRON_SECRET:
        raise AuthorizationError(message="Generated document cron secret is not configured")
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    provided = secret or bearer or query_secret
    if provided != settings.GENERATED_DOCUMENT_CRON_SECRET:
        raise AuthorizationError(message="Invalid generated document cron secret")


@router.get("", response_model=GeneratedDocumentListResponse)
async def list_generated_documents(
    current_user: CurrentUser,
    db: DB,
    document_type: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    _: None = Depends(require_admin_or_ho_manager),
) -> GeneratedDocumentListResponse:
    service = GeneratedDocumentService(db)
    docs = await service.list_documents(document_type=document_type, start=start, end=end)
    return GeneratedDocumentListResponse(items=docs, total=len(docs))


@router.get("/{document_id}/download")
async def download_generated_document(
    document_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> StreamingResponse:
    service = GeneratedDocumentService(db)
    doc = await service.get_by_id(document_id)
    if not doc:
        raise NotFoundError(resource="GeneratedDocument", resource_id=document_id)
    return StreamingResponse(
        iter([doc.content]),
        media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.post("/monthly/send", response_model=MonthlyDocumentEmailResponse)
async def send_monthly_documents(
    current_user: CurrentUser,
    db: DB,
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    _: None = Depends(require_admin),
) -> MonthlyDocumentEmailResponse:
    service = GeneratedDocumentService(db)
    result = await service.send_monthly_zip_to_admins(
        year=year,
        month=month,
        generated_by_id=current_user.id,
    )
    return MonthlyDocumentEmailResponse(**result)


@router.delete("/expired", response_model=CleanupGeneratedDocumentsResponse)
async def cleanup_expired_generated_documents(
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> CleanupGeneratedDocumentsResponse:
    service = GeneratedDocumentService(db)
    deleted_count = await service.cleanup_expired()
    return CleanupGeneratedDocumentsResponse(deleted_count=deleted_count)


@router.post("/monthly/cron", response_model=MonthlyDocumentEmailResponse)
async def send_previous_month_documents_from_cron(
    db: DB,
    x_cron_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
) -> MonthlyDocumentEmailResponse:
    _validate_cron_secret(x_cron_secret, authorization, secret)
    previous_month_last = date.today().replace(day=1) - timedelta(days=1)
    service = GeneratedDocumentService(db)
    result = await service.send_monthly_zip_to_admins(
        year=previous_month_last.year,
        month=previous_month_last.month,
    )
    return MonthlyDocumentEmailResponse(**result)


@router.delete("/expired/cron", response_model=CleanupGeneratedDocumentsResponse)
async def cleanup_expired_generated_documents_from_cron(
    db: DB,
    x_cron_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
) -> CleanupGeneratedDocumentsResponse:
    _validate_cron_secret(x_cron_secret, authorization, secret)
    service = GeneratedDocumentService(db)
    deleted_count = await service.cleanup_expired()
    return CleanupGeneratedDocumentsResponse(deleted_count=deleted_count)


@router.get("/monthly/cron", response_model=MonthlyDocumentEmailResponse)
async def send_previous_month_documents_from_cron_get(
    db: DB,
    x_cron_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
) -> MonthlyDocumentEmailResponse:
    _validate_cron_secret(x_cron_secret, authorization, secret)
    previous_month_last = date.today().replace(day=1) - timedelta(days=1)
    service = GeneratedDocumentService(db)
    result = await service.send_monthly_zip_to_admins(
        year=previous_month_last.year,
        month=previous_month_last.month,
    )
    return MonthlyDocumentEmailResponse(**result)


@router.get("/expired/cron", response_model=CleanupGeneratedDocumentsResponse)
async def cleanup_expired_generated_documents_from_cron_get(
    db: DB,
    x_cron_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
) -> CleanupGeneratedDocumentsResponse:
    _validate_cron_secret(x_cron_secret, authorization, secret)
    service = GeneratedDocumentService(db)
    deleted_count = await service.cleanup_expired()
    return CleanupGeneratedDocumentsResponse(deleted_count=deleted_count)
