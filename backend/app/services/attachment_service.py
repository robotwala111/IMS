"""
Attachment Service

Handles file upload and attachment management.
"""

import re
import uuid
import hashlib
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.attachment import Attachment
from app.services.base_service import BaseService


class AttachmentService(BaseService[Attachment]):
    """Service for file attachment management."""

    MAX_FILE_SIZE = 10 * 1024 * 1024
    
    @property
    def model(self):
        return Attachment
    
    def _get_storage_path(self) -> Path:
        """Get the base storage path for files."""
        return Path(settings.STORAGE_LOCAL_PATH)
    
    def _generate_filename(self, original_filename: str) -> str:
        """Generate a unique filename for storage."""
        ext = Path(original_filename).suffix
        unique_id = str(uuid.uuid4())
        return f"{unique_id}{ext}"

    @staticmethod
    def validate_filename(filename: Optional[str]) -> str:
        if not filename or filename in {".", ".."}:
            raise BadRequestError(message="A valid filename is required")
        if any(char in filename for char in ("/", "\\", "\x00")):
            raise BadRequestError(message="Filename must not contain path separators")
        if any(ord(char) < 32 for char in filename):
            raise BadRequestError(message="Filename contains invalid control characters")
        if len(filename) > 255:
            raise BadRequestError(message="Filename exceeds 255 characters")
        return filename

    @staticmethod
    def validate_file_signature(content: bytes, content_type: Optional[str], filename: str) -> None:
        if b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!" in content:
            raise BadRequestError(message="File contains a known malware test signature")
        extensions = {
            "image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"},
            "image/gif": {".gif"}, "image/webp": {".webp"},
            "application/pdf": {".pdf"}, "application/msword": {".doc"},
            "application/vnd.ms-excel": {".xls"},
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {".xlsx"},
            "text/plain": {".txt"}, "text/csv": {".csv"},
        }
        extension = Path(filename).suffix.lower()
        if content_type not in extensions or extension not in extensions[content_type]:
            raise BadRequestError(message="Filename extension does not match the declared file type")

        if content_type == "image/jpeg":
            valid = content.startswith(b"\xff\xd8\xff")
        elif content_type == "image/png":
            valid = content.startswith(b"\x89PNG\r\n\x1a\n")
        elif content_type == "image/gif":
            valid = content.startswith((b"GIF87a", b"GIF89a"))
        elif content_type == "image/webp":
            valid = len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
        elif content_type == "application/pdf":
            valid = content.startswith(b"%PDF-")
        elif content_type in {"application/msword", "application/vnd.ms-excel"}:
            valid = content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        elif content_type in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }:
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    names = archive.namelist()
                prefix = "word/" if content_type.endswith("wordprocessingml.document") else "xl/"
                valid = "[Content_Types].xml" in names and any(name.startswith(prefix) for name in names)
            except (zipfile.BadZipFile, OSError):
                valid = False
        else:
            try:
                content.decode("utf-8-sig")
                valid = b"\x00" not in content
            except UnicodeDecodeError:
                valid = False
        if not valid:
            raise BadRequestError(message="File content does not match the declared file type")
    
    def _get_entity_path(self, entity_type: str, entity_id: str) -> Path:
        """Get the storage path for an entity's attachments.

        Both *entity_type* and *entity_id* are sanitised to alphanumeric +
        hyphens/underscores only so that path-traversal payloads like
        ``../../etc/passwd`` are rejected before ever reaching the filesystem.
        """
        # Allow only safe characters – no dots, slashes, or null bytes
        safe_type = re.sub(r"[^a-zA-Z0-9_-]", "", entity_type)
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", entity_id)
        if not safe_type or not safe_id or safe_type != entity_type or safe_id != entity_id:
            raise BadRequestError(message="Invalid entity type or ID for file storage")
        base = self._get_storage_path()
        target = base / safe_type / safe_id
        # Resolved path must still be inside the configured storage root
        if not target.resolve().is_relative_to(base.resolve()):
            raise BadRequestError(message="Invalid file storage path")
        return target

    def _validated_stored_path(self, storage_key: str) -> Path:
        path = Path(storage_key).resolve()
        if not path.is_relative_to(self._get_storage_path().resolve()):
            raise BadRequestError(message="Attachment storage path is invalid")
        return path
    
    async def get_by_id(self, id: str) -> Optional[Attachment]:
        """Get attachment with uploader info."""
        result = await self.db.execute(
            select(Attachment)
            .options(selectinload(Attachment.uploaded_by))
            .where(Attachment.id == id)
        )
        return result.scalar_one_or_none()
    
    async def upload(
        self,
        file: UploadFile,
        entity_type: str,
        entity_id: str,
        uploaded_by_id: str,
        description: Optional[str] = None,
    ) -> Attachment:
        """
        Upload a file and create an attachment record.
        
        Args:
            file: Uploaded file
            entity_type: Type of entity (item, asset, calibration, maintenance)
            entity_id: ID of the entity
            uploaded_by_id: User uploading the file
            description: Optional description
            
        Returns:
            Created attachment record
        """
        # Read file content
        content = await file.read()
        file_size = len(content)
        if file_size > self.MAX_FILE_SIZE:
            raise BadRequestError(message="File size exceeds maximum of 10MB")
        original_filename = self.validate_filename(file.filename)
        self.validate_file_signature(content, file.content_type, original_filename)
        checksum = hashlib.sha256(content).hexdigest()

        duplicate = await self.db.execute(
            select(Attachment.id).where(
                Attachment.entity_type == entity_type,
                Attachment.entity_id == entity_id,
                Attachment.checksum == checksum,
            ).limit(1)
        )
        if duplicate.scalar_one_or_none():
            raise BadRequestError(message="This file is already attached to the record")
        
        # Generate storage filename
        stored_filename = self._generate_filename(original_filename)
        
        # Create storage directory
        storage_path = self._get_entity_path(entity_type, entity_id)
        storage_path.mkdir(parents=True, exist_ok=True)
        
        # Save file
        file_path = storage_path / stored_filename
        with open(file_path, "wb") as f:
            f.write(content)
        
        # Create attachment record
        attachment = Attachment(
            id=self.generate_id(),
            original_filename=original_filename,
            content_type=file.content_type,
            size_bytes=file_size,
            storage_key=str(file_path),
            entity_type=entity_type,
            entity_id=entity_id,
            category=entity_type,
            checksum=checksum,
            description=description,
            uploaded_by_id=uploaded_by_id,
            uploaded_at=datetime.now(timezone.utc),
        )
        
        self.db.add(attachment)
        try:
            await self.db.commit()
            await self.db.refresh(attachment)
        except Exception:
            await self.db.rollback()
            file_path.unlink(missing_ok=True)
            raise
        
        return attachment
    
    async def get_file_path(self, attachment_id: str) -> Optional[str]:
        """Get the file path for an attachment."""
        attachment = await self.get_by_id(attachment_id)
        if not attachment:
            return None
        
        path = self._validated_stored_path(attachment.storage_key)
        if not path.exists():
            return None
        
        return str(path)
    
    async def list_by_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> List[Attachment]:
        """List all attachments for an entity."""
        result = await self.db.execute(
            select(Attachment)
            .options(selectinload(Attachment.uploaded_by))
            .where(
                Attachment.entity_type == entity_type,
                Attachment.entity_id == entity_id,
            )
            .order_by(Attachment.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def delete(self, attachment_id: str) -> bool:
        """Delete an attachment and its file."""
        attachment = await self.get_by_id(attachment_id)
        if not attachment:
            raise NotFoundError(resource="Attachment", resource_id=attachment_id)
        
        # Delete file if exists
        file_path = self._validated_stored_path(attachment.storage_key)
        if file_path.exists():
            file_path.unlink()
        
        # Delete record
        await self.db.delete(attachment)
        await self.db.commit()
        
        return True
    
    async def delete_by_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> int:
        """Delete all attachments for an entity."""
        attachments = await self.list_by_entity(entity_type, entity_id)
        
        count = 0
        for attachment in attachments:
            file_path = self._validated_stored_path(attachment.storage_key)
            if file_path.exists():
                file_path.unlink()
            await self.db.delete(attachment)
            count += 1
        
        await self.db.commit()
        
        return count
