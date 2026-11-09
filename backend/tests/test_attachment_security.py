"""Attachment content and storage security regression tests."""

import io
import zipfile

import pytest
from fastapi import UploadFile
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import BadRequestError
from app.services.attachment_service import AttachmentService


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("report.pdf", "application/pdf", b"%PDF-1.7\ncontent"),
        ("photo.jpg", "image/jpeg", b"\xff\xd8\xff\xe0content"),
        ("image.png", "image/png", b"\x89PNG\r\n\x1a\ncontent"),
        ("notes.txt", "text/plain", b"plain text"),
        ("data.csv", "text/csv", b"name,value\na,1\n"),
    ],
)
def test_valid_file_signatures(filename, content_type, content):
    AttachmentService.validate_file_signature(content, content_type, filename)


def test_valid_office_open_xml_signature():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
    AttachmentService.validate_file_signature(
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "report.docx",
    )


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("fake.pdf", "application/pdf", b"not a pdf"),
        ("renamed.jpg", "image/jpeg", b"%PDF-1.7"),
        ("sheet.pdf", "text/csv", b"a,b\n1,2"),
        ("broken.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PKfake"),
    ],
)
def test_mislabeled_content_is_rejected(filename, content_type, content):
    with pytest.raises(BadRequestError):
        AttachmentService.validate_file_signature(content, content_type, filename)


@pytest.mark.parametrize(
    "filename", ["../secret.pdf", "..\\secret.pdf", "folder/file.pdf", "bad\x00.pdf", "bad\n.pdf"]
)
def test_unsafe_filenames_are_rejected(filename):
    with pytest.raises(BadRequestError):
        AttachmentService.validate_filename(filename)


@pytest.mark.parametrize("entity_value", ["../asset", "asset/child", "asset.child", "asset\\child"])
def test_entity_path_traversal_is_rejected(tmp_path, monkeypatch, entity_value):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    service = AttachmentService(None)
    with pytest.raises(BadRequestError):
        service._get_entity_path("asset", entity_value)


def test_eicar_malware_test_file_is_rejected():
    eicar = (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"
        b"$H+H*"
    )
    with pytest.raises(BadRequestError, match="malware"):
        AttachmentService.validate_file_signature(eicar, "text/plain", "eicar.txt")


@pytest.mark.asyncio
async def test_duplicate_content_for_same_entity_is_rejected(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    db = MagicMock()
    db.execute = AsyncMock()
    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = "existing-attachment"
    db.execute.return_value = duplicate_result
    service = AttachmentService(db)
    upload = UploadFile(filename="report.pdf", file=io.BytesIO(b"%PDF-1.7\ncontent"))
    upload.headers = {"content-type": "application/pdf"}

    with pytest.raises(BadRequestError, match="already attached"):
        await service.upload(upload, "asset", "asset-1", "user-1")
    assert not list(tmp_path.rglob("*.pdf"))


@pytest.mark.asyncio
async def test_database_failure_removes_orphaned_disk_file(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_LOCAL_PATH", str(tmp_path))
    db = MagicMock()
    db.execute = AsyncMock()
    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = None
    db.execute.return_value = duplicate_result
    db.commit = AsyncMock(side_effect=RuntimeError("database unavailable"))
    db.rollback = AsyncMock()
    service = AttachmentService(db)
    upload = UploadFile(filename="report.pdf", file=io.BytesIO(b"%PDF-1.7\ncontent"))
    upload.headers = {"content-type": "application/pdf"}

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.upload(upload, "asset", "asset-1", "user-1")
    db.rollback.assert_awaited_once()
    assert not list(tmp_path.rglob("*.pdf"))
