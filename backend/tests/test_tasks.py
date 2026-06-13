"""
Unit tests for tasks/embedding.py — the process_document Celery task.

All DB calls, PDF extraction, chunking, and embedding are intercepted via
monkeypatch. No real database, no real API calls, no Celery worker needed.
Tests call _do_process_document directly to bypass the Celery decorator.
"""

import uuid
from unittest.mock import MagicMock, call

import pytest

import app.tasks.embedding as tasks_module
from app.tasks.embedding import _do_process_document
from app.models.chunk import Chunk
from app.models.document import DocumentStatus, SourceType
from app.utils.chunking import TextChunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(
    status: DocumentStatus = DocumentStatus.processing,
    content: str = "First sentence. Second sentence. Third sentence.",
    file_path: str | None = None,
) -> MagicMock:
    """Build a mock Document with sensible defaults."""
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.status = status
    doc.content = content
    doc.file_path = file_path
    return doc


def _make_chunks(n: int = 3) -> list[TextChunk]:
    return [
        TextChunk(content=f"Chunk content {i}.", chunk_index=i, token_count=10)
        for i in range(n)
    ]


def _make_vectors(n: int = 3) -> list[list[float]]:
    return [[float(i) / 10] * 1536 for i in range(n)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_db(monkeypatch):
    """Replace SessionLocal with a mock session."""
    session = MagicMock()
    monkeypatch.setattr(tasks_module, "SessionLocal", lambda: session)
    return session


@pytest.fixture()
def mock_extract(monkeypatch):
    """Replace extract_text_from_pdf with a function returning fake text."""
    monkeypatch.setattr(
        tasks_module,
        "extract_text_from_pdf",
        lambda path: "Extracted PDF sentence one. Extracted PDF sentence two.",
    )


@pytest.fixture()
def mock_pipeline(monkeypatch):
    """Mock both chunk_text and embed_chunks together so counts always match."""
    chunks = _make_chunks(3)
    vectors = _make_vectors(3)
    monkeypatch.setattr(tasks_module, "chunk_text", lambda text: chunks)
    monkeypatch.setattr(tasks_module, "embed_chunks", lambda c: vectors[: len(c)])
    return chunks, vectors


# ---------------------------------------------------------------------------
# Happy path — TXT / plain content
# ---------------------------------------------------------------------------

def test_txt_document_is_marked_ready(mock_db, mock_pipeline):
    doc = _make_doc()
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    assert doc.status == DocumentStatus.ready


def test_txt_document_commits(mock_db, mock_pipeline):
    doc = _make_doc()
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    mock_db.commit.assert_called()


def test_chunk_records_are_bulk_inserted(mock_db, mock_pipeline):
    doc = _make_doc()
    mock_db.get.return_value = doc
    chunks, _ = mock_pipeline

    _do_process_document(str(doc.id))

    mock_db.add_all.assert_called_once()
    inserted = mock_db.add_all.call_args[0][0]
    assert len(inserted) == len(chunks)


def test_chunk_records_are_chunk_instances(mock_db, mock_pipeline):
    doc = _make_doc()
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    inserted = mock_db.add_all.call_args[0][0]
    assert all(isinstance(c, Chunk) for c in inserted)


def test_chunk_records_have_correct_document_id(mock_db, mock_pipeline):
    doc = _make_doc()
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    inserted = mock_db.add_all.call_args[0][0]
    assert all(c.document_id == doc.id for c in inserted)


def test_chunk_records_store_correct_indices(mock_db, mock_pipeline):
    doc = _make_doc()
    mock_db.get.return_value = doc
    chunks, _ = mock_pipeline

    _do_process_document(str(doc.id))

    inserted = mock_db.add_all.call_args[0][0]
    assert [c.chunk_index for c in inserted] == [ch.chunk_index for ch in chunks]


# ---------------------------------------------------------------------------
# Happy path — PDF
# ---------------------------------------------------------------------------

def test_pdf_calls_extract_text_from_pdf(mock_db, mock_pipeline, mock_extract, monkeypatch):
    spy = MagicMock(return_value="PDF text one. PDF text two.")
    monkeypatch.setattr(tasks_module, "extract_text_from_pdf", spy)
    doc = _make_doc(content="", file_path="/uploads/abc.pdf")
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    spy.assert_called_once()


def test_pdf_extracted_text_is_stored_on_document(mock_db, mock_pipeline, mock_extract):
    doc = _make_doc(content="", file_path="/uploads/abc.pdf")
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    assert doc.content != ""


def test_pdf_document_is_marked_ready(mock_db, mock_pipeline, mock_extract):
    doc = _make_doc(content="", file_path="/uploads/abc.pdf")
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    assert doc.status == DocumentStatus.ready


# ---------------------------------------------------------------------------
# Early-exit cases
# ---------------------------------------------------------------------------

def test_document_not_found_returns_without_error(mock_db):
    mock_db.get.return_value = None
    _do_process_document(str(uuid.uuid4()))  # should not raise


def test_document_not_found_makes_no_commit(mock_db):
    mock_db.get.return_value = None
    _do_process_document(str(uuid.uuid4()))
    mock_db.commit.assert_not_called()


def test_already_ready_document_is_skipped(mock_db, mock_pipeline):
    doc = _make_doc(status=DocumentStatus.ready)
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    mock_db.add_all.assert_not_called()


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------

def test_empty_text_sets_status_failed(mock_db, mock_pipeline):
    doc = _make_doc(content="   ")
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    assert doc.status == DocumentStatus.failed


def test_pdf_extraction_failure_sets_status_failed(mock_db, mock_pipeline, monkeypatch):
    monkeypatch.setattr(
        tasks_module,
        "extract_text_from_pdf",
        lambda path: (_ for _ in ()).throw(ValueError("corrupt PDF")),
    )
    doc = _make_doc(content="", file_path="/uploads/bad.pdf")
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    assert doc.status == DocumentStatus.failed


def test_embedding_error_sets_status_failed(mock_db, monkeypatch):
    chunks = _make_chunks(2)
    monkeypatch.setattr(tasks_module, "chunk_text", lambda text: chunks)
    monkeypatch.setattr(
        tasks_module,
        "embed_chunks",
        lambda c: (_ for _ in ()).throw(RuntimeError("rate limit")),
    )
    doc = _make_doc()
    mock_db.get.return_value = doc

    _do_process_document(str(doc.id))

    assert doc.status == DocumentStatus.failed


def test_db_close_always_called_on_success(mock_db, mock_pipeline):
    doc = _make_doc()
    mock_db.get.return_value = doc
    _do_process_document(str(doc.id))
    mock_db.close.assert_called_once()


def test_db_close_always_called_on_failure(mock_db, monkeypatch):
    monkeypatch.setattr(
        tasks_module,
        "chunk_text",
        lambda text: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    doc = _make_doc()
    mock_db.get.return_value = doc
    _do_process_document(str(doc.id))
    mock_db.close.assert_called_once()
