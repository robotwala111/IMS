"""
Attachments Endpoints

File upload and attachment management.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from fastapi.responses import FileResponse

from app.api.v1.dependencies import CurrentUser, DB, require_location_access
from app.core.exceptions import NotFoundError, BadRequestError
from app.core.logging import get_logger
from app.core.config import settings
from app.schemas.common import MessageResponse
from app.schemas.attachment import (
    AttachmentResponse,
    AttachmentListResponse,
)
from app.services.attachment_service import AttachmentService
from app.services.audit_service import AuditService

logger = get_logger(__name__)
router = APIRouter()


ALLOWED_MIME_TYPES = [
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "text/csv",
]

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


async def _require_entity_access(current_user, db, entity_type: str, entity_id: str) -> None:
    """Authorize attachment access through the parent entity's location."""
    if not entity_type or not entity_id:
        raise NotFoundError(resource="Attachment parent")
    if entity_type == "item":
        # Item definitions are company-wide; stock rows remain location-scoped.
        from app.services.item_service import ItemService
        entity = await ItemService(db).get_by_id(entity_id)
        if not entity:
            raise NotFoundError(resource="Item", resource_id=entity_id)
        return

    from app.services.asset_service import AssetService
    asset = None
    if entity_type == "asset":
        asset = await AssetService(db).get_by_id(entity_id)
    elif entity_type == "calibration":
        from app.services.calibration_service import CalibrationService
        record = await CalibrationService(db).get_by_id(entity_id)
        if record:
            asset = await AssetService(db).get_by_id(record.asset_id)
    elif entity_type == "maintenance":
        from app.services.maintenance_service import MaintenanceService
        record = await MaintenanceService(db).get_by_id(entity_id)
        if record:
            asset = await AssetService(db).get_by_id(record.asset_id)

    if not asset:
        raise NotFoundError(resource=entity_type.title(), resource_id=entity_id)
    require_location_access(current_user, asset.location_id)


@router.post("/upload", response_model=AttachmentResponse, status_code=201)
async def upload_attachment(
    current_user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    entity_type: str = Form(..., description="item, asset, calibration, maintenance"),
    entity_id: str = Form(...),
    description: Optional[str] = Form(None),
) -> AttachmentResponse:
    """
    Upload an attachment for an entity.
    """
    attachment_service = AttachmentService(db)
    audit_service = AuditService(db)
    
    # Validate file type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise BadRequestError(
            message=f"File type {file.content_type} is not allowed",
            details={"allowed_types": ALLOWED_MIME_TYPES},
        )
    
    # Validate file size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise BadRequestError(
            message=f"File size exceeds maximum of {MAX_FILE_SIZE // (1024*1024)}MB",
        )
    
    # Reset file position after reading
    await file.seek(0)
    
    # Validate entity type
    valid_entity_types = ["item", "asset", "calibration", "maintenance"]
    if entity_type not in valid_entity_types:
        raise BadRequestError(
            message=f"Invalid entity type: {entity_type}",
            details={"valid_types": valid_entity_types},
        )

    await _require_entity_access(current_user, db, entity_type, entity_id)
    
    # Create attachment
    attachment = await attachment_service.upload(
        file=file,
        entity_type=entity_type,
        entity_id=entity_id,
        uploaded_by_id=current_user.id,
        description=description,
    )
    
    # Audit log
    await audit_service.log_action(
        action="upload_attachment",
        resource_type=entity_type,
        resource_id=entity_id,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "attachment_id": attachment.id,
            "filename": attachment.original_filename,
            "size": attachment.size_bytes,
        },
    )
    
    return attachment


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    attachment_id: str,
    current_user: CurrentUser,
    db: DB,
) -> AttachmentResponse:
    """
    Get attachment metadata by ID.
    """
    attachment_service = AttachmentService(db)
    attachment = await attachment_service.get_by_id(attachment_id)
    
    if not attachment:
        raise NotFoundError(resource="Attachment", resource_id=attachment_id)
    await _require_entity_access(
        current_user, db, attachment.entity_type, attachment.entity_id
    )

    return attachment


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: str,
    current_user: CurrentUser,
    db: DB,
) -> FileResponse:
    """
    Download an attachment file.
    """
    attachment_service = AttachmentService(db)
    attachment = await attachment_service.get_by_id(attachment_id)
    
    if not attachment:
        raise NotFoundError(resource="Attachment", resource_id=attachment_id)
    await _require_entity_access(
        current_user, db, attachment.entity_type, attachment.entity_id
    )

    file_path = await attachment_service.get_file_path(attachment_id)
    
    if not file_path:
        await AuditService(db).log_action(
            action="download", resource_type="attachment", resource_id=attachment.id,
            user_id=current_user.id, new_value={"filename": attachment.original_filename},
            status="failure", error_message="File not found on disk",
        )
        raise NotFoundError(
            resource="Attachment file",
            resource_id=attachment_id,
            message="File not found on disk",
        )
    
    await AuditService(db).log_action(
        action="download", resource_type="attachment", resource_id=attachment.id,
        user_id=current_user.id,
        new_value={
            "filename": attachment.original_filename,
            "entity_type": attachment.entity_type, "entity_id": attachment.entity_id,
        },
    )
    return FileResponse(
        path=file_path,
        filename=attachment.original_filename,
        media_type=attachment.content_type,
    )


@router.delete("/{attachment_id}", response_model=MessageResponse)
async def delete_attachment(
    attachment_id: str,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Delete an attachment.
    """
    attachment_service = AttachmentService(db)
    audit_service = AuditService(db)
    
    attachment = await attachment_service.get_by_id(attachment_id)
    if not attachment:
        raise NotFoundError(resource="Attachment", resource_id=attachment_id)
    await _require_entity_access(
        current_user, db, attachment.entity_type, attachment.entity_id
    )
    
    # Only uploader or admin can delete
    if attachment.uploaded_by_id != current_user.id and not current_user.is_admin:
        raise NotFoundError(resource="Attachment", resource_id=attachment_id)
    
    old_data = {
        "filename": attachment.original_filename,
        "entity_type": attachment.entity_type,
        "entity_id": attachment.entity_id,
    }
    
    await attachment_service.delete(attachment_id)
    
    # Audit log
    await audit_service.log_action(
        action="delete_attachment",
        resource_type=attachment.entity_type,
        resource_id=attachment.entity_id,
        user_id=current_user.id,
        old_value=old_data,
        new_value=None,
    )
    
    return MessageResponse(message="Attachment deleted successfully")


@router.get("/entity/{entity_type}/{entity_id}", response_model=AttachmentListResponse)
async def list_entity_attachments(
    entity_type: str,
    entity_id: str,
    current_user: CurrentUser,
    db: DB,
) -> AttachmentListResponse:
    """
    List all attachments for a specific entity.
    """
    attachment_service = AttachmentService(db)
    
    valid_entity_types = ["item", "asset", "calibration", "maintenance"]
    if entity_type not in valid_entity_types:
        raise BadRequestError(
            message=f"Invalid entity type: {entity_type}",
            details={"valid_types": valid_entity_types},
        )

    await _require_entity_access(current_user, db, entity_type, entity_id)
    
    attachments = await attachment_service.list_by_entity(
        entity_type=entity_type,
        entity_id=entity_id,
    )
    
    return AttachmentListResponse(
        items=attachments,
        total=len(attachments),
        page=1,
        page_size=len(attachments),
        pages=1,
    )
