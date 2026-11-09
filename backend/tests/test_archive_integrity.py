"""Archive artifact integrity and recoverability-contract tests."""

import hashlib
import io
import json
import zipfile
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.services.archive_service import build_archive, verify_archive


@pytest_asyncio.fixture
async def archive_sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_generated_archive_round_trip_is_structurally_verified(archive_sessions):
    artifact = await build_archive(
        datetime(2026, 1, 1), datetime(2026, 3, 31, 23, 59, 59),
        include_attachments=False, session_factory=archive_sessions,
    )

    manifest = verify_archive(artifact)

    assert manifest["format_version"] == 1
    assert manifest["archive_kind"] == "audit_export_not_database_backup"
    assert manifest["record_counts"]["Transactions"] == 0
    assert any(name.endswith("archive_data.xlsx") for name in manifest["files"])


def test_verifier_rejects_checksum_mismatch():
    workbook_name = "archive_20260101-20260331/archive_data.xlsx"
    manifest_name = "archive_20260101-20260331/manifest.json"
    manifest = {
        "format_version": 1,
        "files": {workbook_name: hashlib.sha256(b"original").hexdigest()},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(workbook_name, b"tampered")
        archive.writestr(manifest_name, json.dumps(manifest))

    with pytest.raises(ValueError, match="Checksum mismatch"):
        verify_archive(buffer.getvalue())


def test_verifier_rejects_archive_without_manifest():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("archive/data.txt", b"data")

    with pytest.raises(ValueError, match="manifest"):
        verify_archive(buffer.getvalue())
