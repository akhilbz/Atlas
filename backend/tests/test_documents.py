"""
Document endpoint tests (Phase 2, Pieces 1 & 6).

Coverage:
  upload      — file types, validation, auth, response shape, user isolation
  list        — empty state, pagination, cursor, ordering, user isolation, auth
  get         — happy path, 404 for unknown/other-user's doc, auth
  delete      — 204 success, removes from list, 404, auth
"""

import io
import uuid
from unittest.mock import patch

import pytest


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


def test_upload_without_file_field_returns_422(client, auth_headers):
    """Sending no file at all must be rejected by FastAPI's parameter validation."""
    resp = client.post("/api/documents/upload", headers=auth_headers)
    assert resp.status_code == 422


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


# ---------------------------------------------------------------------------
# Celery mock — prevents real Redis dispatch for every test in this module
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_celery(monkeypatch):
    """Replace process_document.delay with a no-op so tests need no Redis."""
    with patch("app.routes.documents.process_document") as m:
        m.delay.return_value = None
        yield m


# ---------------------------------------------------------------------------
# Shared helpers for library endpoint tests
# ---------------------------------------------------------------------------

def _upload(client, headers, name="doc.txt", content="Sample. Content."):
    resp = client.post("/api/documents/upload", files=_txt(content=content, name=name), headers=headers)
    assert resp.status_code == 201
    return resp.json()


def _make_other_headers(client):
    client.post("/api/auth/signup", json={"email": "other@test.com", "password": "pass1234"})
    resp = client.post("/api/auth/login", json={"email": "other@test.com", "password": "pass1234"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# GET /api/documents — list
# ---------------------------------------------------------------------------

def test_list_returns_200(client, auth_headers):
    resp = client.get("/api/documents", headers=auth_headers)
    assert resp.status_code == 200


def test_list_empty_when_no_documents(client, auth_headers):
    body = client.get("/api/documents", headers=auth_headers).json()
    assert body["items"] == []
    assert body["next_cursor"] is None


def test_list_returns_uploaded_document(client, auth_headers):
    doc = _upload(client, auth_headers, name="paper.txt")
    ids = [d["id"] for d in client.get("/api/documents", headers=auth_headers).json()["items"]]
    assert doc["id"] in ids


def test_list_returns_all_user_documents(client, auth_headers):
    _upload(client, auth_headers, name="a.txt")
    _upload(client, auth_headers, name="b.txt")
    assert len(client.get("/api/documents", headers=auth_headers).json()["items"]) == 2


def test_list_ordered_newest_first(client, auth_headers):
    _upload(client, auth_headers, name="first.txt")
    _upload(client, auth_headers, name="second.txt")
    dates = [d["created_at"] for d in client.get("/api/documents", headers=auth_headers).json()["items"]]
    assert dates == sorted(dates, reverse=True)


def test_list_excludes_other_users_documents(client, auth_headers):
    other = _make_other_headers(client)
    _upload(client, other, name="theirs.txt")
    assert client.get("/api/documents", headers=auth_headers).json()["items"] == []


def test_list_requires_auth(client):
    assert client.get("/api/documents").status_code == 403


def test_list_next_cursor_none_when_all_fit(client, auth_headers):
    _upload(client, auth_headers)
    body = client.get("/api/documents", headers=auth_headers, params={"limit": 10}).json()
    assert body["next_cursor"] is None


def test_list_next_cursor_present_when_overflow(client, auth_headers):
    _upload(client, auth_headers, name="x.txt")
    _upload(client, auth_headers, name="y.txt")
    body = client.get("/api/documents", headers=auth_headers, params={"limit": 1}).json()
    assert body["next_cursor"] is not None


def test_list_cursor_pagination_fetches_second_page(client, auth_headers):
    _upload(client, auth_headers, name="first.txt")
    _upload(client, auth_headers, name="second.txt")
    page1 = client.get("/api/documents", headers=auth_headers, params={"limit": 1}).json()
    cursor = page1["next_cursor"]
    page2 = client.get("/api/documents", headers=auth_headers, params={"limit": 1, "cursor": cursor}).json()
    assert len(page2["items"]) == 1
    assert page2["items"][0]["id"] != page1["items"][0]["id"]


def test_list_invalid_cursor_returns_400(client, auth_headers):
    resp = client.get("/api/documents", headers=auth_headers, params={"cursor": "not-valid!!"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/documents/{id} — detail
# ---------------------------------------------------------------------------

def test_get_document_returns_200(client, auth_headers):
    doc = _upload(client, auth_headers)
    assert client.get(f"/api/documents/{doc['id']}", headers=auth_headers).status_code == 200


def test_get_document_returns_correct_id(client, auth_headers):
    doc = _upload(client, auth_headers, name="specific.txt")
    assert client.get(f"/api/documents/{doc['id']}", headers=auth_headers).json()["id"] == doc["id"]


def test_get_nonexistent_document_returns_404(client, auth_headers):
    assert client.get(f"/api/documents/{uuid.uuid4()}", headers=auth_headers).status_code == 404


def test_get_other_users_document_returns_404(client, auth_headers):
    other = _make_other_headers(client)
    doc = _upload(client, other, name="private.txt")
    assert client.get(f"/api/documents/{doc['id']}", headers=auth_headers).status_code == 404


def test_get_document_requires_auth(client, auth_headers):
    doc = _upload(client, auth_headers)
    assert client.get(f"/api/documents/{doc['id']}").status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/documents/{id}
# ---------------------------------------------------------------------------

def test_delete_document_returns_204(client, auth_headers):
    doc = _upload(client, auth_headers)
    assert client.delete(f"/api/documents/{doc['id']}", headers=auth_headers).status_code == 204


def test_delete_removes_document_from_list(client, auth_headers):
    doc = _upload(client, auth_headers)
    client.delete(f"/api/documents/{doc['id']}", headers=auth_headers)
    ids = [d["id"] for d in client.get("/api/documents", headers=auth_headers).json()["items"]]
    assert doc["id"] not in ids


def test_delete_nonexistent_document_returns_404(client, auth_headers):
    assert client.delete(f"/api/documents/{uuid.uuid4()}", headers=auth_headers).status_code == 404


def test_delete_other_users_document_returns_404(client, auth_headers):
    other = _make_other_headers(client)
    doc = _upload(client, other, name="notmine.txt")
    assert client.delete(f"/api/documents/{doc['id']}", headers=auth_headers).status_code == 404


def test_delete_requires_auth(client, auth_headers):
    doc = _upload(client, auth_headers)
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 403
