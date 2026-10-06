import io
import asyncio

import pytest
from fastapi import HTTPException, UploadFile

import backend.app as app_module


def test_resume_upload_uses_safe_generated_filename(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "UPLOADS_DIR", tmp_path)
    upload = UploadFile(filename="../../resume.pdf", file=io.BytesIO(b"resume contents"))

    result = asyncio.run(app_module.upload_resume(upload))

    stored = tmp_path / result["path"].split("/")[-1]
    assert result["filename"] == "resume.pdf"
    assert stored.parent == tmp_path
    assert stored.suffix == ".pdf"
    assert stored.read_bytes() == b"resume contents"


def test_resume_upload_rejects_unsupported_file_type(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "UPLOADS_DIR", tmp_path)
    upload = UploadFile(filename="resume.exe", file=io.BytesIO(b"not a resume"))

    with pytest.raises(HTTPException, match="PDF, DOCX, or TXT"):
        asyncio.run(app_module.upload_resume(upload))
