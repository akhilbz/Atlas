"""
Document upload endpoint tests (Phase 2, Piece 1).

Coverage:
  file types  — txt, md accepted and marked ready; pdf accepted and marked processing
  validation  — wrong extension, oversized file, non-UTF-8 text, missing file
  auth        — unauthenticated request rejected
  response    — correct shape, title derived from filename, sensitive fields excluded
  isolation   — documents are scoped to the uploading user
"""

import io


# ---------------------------------------------------------------------------
# Helpers — build in-memory file payloads for multipart upload
# ---------------------------------------------------------------------------

def _txt(content: str = "Hello world. This is a plain text document.", name: str = "test.txt") -> dict:
    return {"file": (name, io.BytesIO(content.encode("utf-8")), "text/plain")}


def _md(content: str = "# Title\n\nSome **markdown** content.", name: str = "test.md") -> dict:
    return {"file": (name, io.BytesIO(content.encode("utf-8")), "text/markdown")}


def _pdf(size_bytes: int = 512, name: str = "test.pdf") -> dict:
    content = b"%PDF-1.4 " + b"x" * size_bytes
    return {"file": (name, io.BytesIO(content), "application/pdf")}


# ---------------------------------------------------------------------------
# Successful uploads
# ---------------------------------------------------------------------------

def test_upload_txt_returns_201(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_txt(), headers=auth_headers)
    assert resp.status_code == 201


def test_upload_txt_status_is_ready(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_txt(), headers=auth_headers)
    assert resp.json()["status"] == "ready"


def test_upload_md_returns_201(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_md(), headers=auth_headers)
    assert resp.status_code == 201


def test_upload_md_status_is_ready(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_md(), headers=auth_headers)
    assert resp.json()["status"] == "ready"


def test_upload_pdf_returns_201(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_pdf(), headers=auth_headers)
    assert resp.status_code == 201


def test_upload_pdf_status_is_processing(client, auth_headers):
    """PDFs are not processed inline — they wait for the Celery worker."""
    resp = client.post("/api/documents/upload", files=_pdf(), headers=auth_headers)
    assert resp.json()["status"] == "processing"


def test_upload_source_type_is_upload(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_txt(), headers=auth_headers)
    assert resp.json()["source_type"] == "upload"


# ---------------------------------------------------------------------------
# Title derivation
# ---------------------------------------------------------------------------

def test_title_derived_from_filename(client, auth_headers):
    files = _txt(name="my_research_paper.txt")
    resp = client.post("/api/documents/upload", files=files, headers=auth_headers)
    assert resp.json()["title"] == "my_research_paper"


def test_title_strips_extension_only(client, auth_headers):
    files = _txt(name="notes.v2.txt")
    resp = client.post("/api/documents/upload", files=files, headers=auth_headers)
    assert resp.json()["title"] == "notes.v2"


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

def test_response_contains_required_fields(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_txt(), headers=auth_headers)
    body = resp.json()
    for field in ("id", "title", "status", "source_type", "tags", "created_at", "updated_at"):
        assert field in body, f"Missing field: {field}"


def test_response_excludes_sensitive_fields(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_txt(), headers=auth_headers)
    body = resp.json()
    assert "content" not in body
    assert "file_path" not in body
    assert "user_id" not in body
    assert "hashed_password" not in body


def test_response_tags_defaults_to_empty_list(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_txt(), headers=auth_headers)
    assert resp.json()["tags"] == []


def test_response_summary_defaults_to_none(client, auth_headers):
    resp = client.post("/api/documents/upload", files=_txt(), headers=auth_headers)
    assert resp.json()["summary"] is None


# ---------------------------------------------------------------------------
# File type validation
# ---------------------------------------------------------------------------

def test_jpg_rejected(client, auth_headers):
    bad = {"file": ("photo.jpg", io.BytesIO(b"\xff\xd8\xff fake jpeg"), "image/jpeg")}
    resp = client.post("/api/documents/upload", files=bad, headers=auth_headers)
    assert resp.status_code == 422


def test_exe_rejected(client, auth_headers):
    bad = {"file": ("virus.exe", io.BytesIO(b"MZ fake exe"), "application/octet-stream")}
    resp = client.post("/api/documents/upload", files=bad, headers=auth_headers)
    assert resp.status_code == 422


def test_no_extension_rejected(client, auth_headers):
    bad = {"file": ("nodotfile", io.BytesIO(b"some content"), "text/plain")}
    resp = client.post("/api/documents/upload", files=bad, headers=auth_headers)
    assert resp.status_code == 422


def test_csv_rejected(client, auth_headers):
    bad = {"file": ("data.csv", io.BytesIO(b"a,b,c\n1,2,3"), "text/csv")}
    resp = client.post("/api/documents/upload", files=bad, headers=auth_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Size validation
# ---------------------------------------------------------------------------

def test_file_exactly_at_limit_accepted(client, auth_headers):
    limit = 20 * 1024 * 1024  # exactly 20MB
    files = {"file": ("big.txt", io.BytesIO(b"x" * limit), "text/plain")}
    resp = client.post("/api/documents/upload", files=files, headers=auth_headers)
    assert resp.status_code == 201


def test_file_over_limit_rejected(client, auth_headers):
    over = 20 * 1024 * 1024 + 1  # 20MB + 1 byte
    files = {"file": ("toobig.txt", io.BytesIO(b"x" * over), "text/plain")}
    resp = client.post("/api/documents/upload", files=files, headers=auth_headers)
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Encoding validation
# ---------------------------------------------------------------------------

def test_non_utf8_txt_rejected(client, auth_headers):
    bad_bytes = b"\xff\xfe invalid latin1 bytes \x80\x81"
    files = {"file": ("bad.txt", io.BytesIO(bad_bytes), "text/plain")}
    resp = client.post("/api/documents/upload", files=files, headers=auth_headers)
    assert resp.status_code == 422


def test_empty_txt_accepted(client, auth_headers):
    """An empty text file is valid — content just happens to be an empty string."""
    resp = client.post("/api/documents/upload", files=_txt(content=""), headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def test_upload_requires_auth(client):
    resp = client.post("/api/documents/upload", files=_txt())
    assert resp.status_code == 403


def test_upload_with_invalid_token_rejected(client):
    resp = client.post(
        "/api/documents/upload",
        files=_txt(),
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# User isolation
# ---------------------------------------------------------------------------

def test_documents_are_scoped_to_uploading_user(client, auth_headers):
    """Two users uploading the same file get separate document records."""
    resp1 = client.post("/api/documents/upload", files=_txt(), headers=auth_headers)

    client.post("/api/auth/signup", json={"email": "other@example.com", "password": "password123"})
    login = client.post("/api/auth/login", json={"email": "other@example.com", "password": "password123"})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp2 = client.post("/api/documents/upload", files=_txt(), headers=other_headers)

    assert resp1.status_code == resp2.status_code == 201
    assert resp1.json()["id"] != resp2.json()["id"]
