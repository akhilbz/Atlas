"""
Unit and integration tests for services/retrieval.py.

_rrf_merge: pure unit tests using MagicMock chunks — no DB needed.
_vector_search / _fts_search: integration tests against the real test DB.
retrieve: end-to-end integration tests with embed_text monkeypatched.
"""

import uuid
from unittest.mock import MagicMock

import pytest

import app.services.retrieval as retrieval_module
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus, SourceType
from app.models.user import User
from app.services.auth import hash_password
from app.services.retrieval import RetrievedChunk, _fts_search, _rrf_merge, _vector_search, retrieve


# ---------------------------------------------------------------------------
# DB fixtures — insert real records so integration tests have data to find
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_user(db):
    user = User(email="retrieval@test.com", hashed_password=hash_password("pass"))
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def other_user(db):
    user = User(email="other@retrieval.test", hashed_password=hash_password("pass"))
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def ready_doc(db, db_user):
    doc = Document(
        user_id=db_user.id,
        title="Attention Is All You Need",
        content="Transformers use self-attention to process sequences.",
        source_type=SourceType.upload,
        status=DocumentStatus.ready,
    )
    db.add(doc)
    db.flush()
    return doc


@pytest.fixture()
def processing_doc(db, db_user):
    doc = Document(
        user_id=db_user.id,
        title="Unpublished Draft",
        content="Still processing.",
        source_type=SourceType.upload,
        status=DocumentStatus.processing,
    )
    db.add(doc)
    db.flush()
    return doc


@pytest.fixture()
def other_doc(db, other_user):
    doc = Document(
        user_id=other_user.id,
        title="Private Doc",
        content="This belongs to another user.",
        source_type=SourceType.upload,
        status=DocumentStatus.ready,
    )
    db.add(doc)
    db.flush()
    return doc


def _unit_vector(dim: int = 1536, hot_index: int = 0) -> list[float]:
    """Return a 1536-d vector with 1.0 at hot_index and 0.0 elsewhere."""
    v = [0.0] * dim
    v[hot_index] = 1.0
    return v


def _make_chunk(db, doc, content: str, index: int = 0, embedding=None) -> Chunk:
    chunk = Chunk(
        document_id=doc.id,
        content=content,
        chunk_index=index,
        token_count=len(content.split()),
        embedding=embedding,
    )
    db.add(chunk)
    db.flush()
    return chunk


# ---------------------------------------------------------------------------
# _rrf_merge — pure unit tests (no DB)
# ---------------------------------------------------------------------------

def _mock_chunk(chunk_id=None):
    m = MagicMock(spec=Chunk)
    m.id = chunk_id or uuid.uuid4()
    return m


def test_rrf_empty_lists_return_empty():
    assert _rrf_merge([], [], top_k=5) == []


def test_rrf_chunk_only_in_vector_list_is_included():
    c = _mock_chunk()
    result = _rrf_merge([c], [], top_k=5)
    assert len(result) == 1
    assert result[0][0] is c


def test_rrf_chunk_only_in_fts_list_is_included():
    c = _mock_chunk()
    result = _rrf_merge([], [c], top_k=5)
    assert len(result) == 1
    assert result[0][0] is c


def test_rrf_chunk_in_both_lists_scores_higher_than_single_list():
    shared = _mock_chunk()
    vector_only = _mock_chunk()
    result = _rrf_merge([shared, vector_only], [shared], top_k=5)
    scores = {r[0].id: r[1] for r in result}
    assert scores[shared.id] > scores[vector_only.id]


def test_rrf_top_k_limits_result_count():
    chunks = [_mock_chunk() for _ in range(10)]
    result = _rrf_merge(chunks, [], top_k=3)
    assert len(result) == 3


def test_rrf_higher_rank_in_list_produces_higher_score():
    first = _mock_chunk()
    second = _mock_chunk()
    result = _rrf_merge([first, second], [], top_k=2)
    assert result[0][0].id == first.id
    assert result[0][1] > result[1][1]


def test_rrf_scores_are_positive_floats():
    c = _mock_chunk()
    result = _rrf_merge([c], [c], top_k=1)
    assert isinstance(result[0][1], float)
    assert result[0][1] > 0


# ---------------------------------------------------------------------------
# _vector_search — integration tests
# ---------------------------------------------------------------------------

def test_vector_search_returns_chunk_with_similar_embedding(db, db_user, ready_doc):
    query_vec = _unit_vector(hot_index=0)
    near = _make_chunk(db, ready_doc, "Near chunk.", embedding=_unit_vector(hot_index=0))
    far = _make_chunk(db, ready_doc, "Far chunk.", embedding=_unit_vector(hot_index=1))

    results = _vector_search(query_vec, db_user.id, db, limit=10)
    ids = [c.id for c in results]

    assert near.id in ids
    assert far.id in ids
    assert ids.index(near.id) < ids.index(far.id)  # near ranks first


def test_vector_search_excludes_chunks_without_embedding(db, db_user, ready_doc):
    _make_chunk(db, ready_doc, "No embedding.", embedding=None)
    results = _vector_search(_unit_vector(), db_user.id, db, limit=10)
    assert all(c.embedding is not None for c in results)


def test_vector_search_excludes_other_users_chunks(db, db_user, other_doc):
    _make_chunk(db, other_doc, "Other user content.", embedding=_unit_vector())
    results = _vector_search(_unit_vector(), db_user.id, db, limit=10)
    assert results == []


def test_vector_search_excludes_non_ready_documents(db, db_user, processing_doc):
    _make_chunk(db, processing_doc, "Processing chunk.", embedding=_unit_vector())
    results = _vector_search(_unit_vector(), db_user.id, db, limit=10)
    assert results == []


def test_vector_search_empty_db_returns_empty(db, db_user):
    assert _vector_search(_unit_vector(), db_user.id, db, limit=10) == []


# ---------------------------------------------------------------------------
# _fts_search — integration tests
# ---------------------------------------------------------------------------

def test_fts_search_returns_matching_chunk(db, db_user, ready_doc):
    chunk = _make_chunk(db, ready_doc, "Transformers use self-attention mechanisms.")
    results = _fts_search("attention", db_user.id, db, limit=10)
    assert any(c.id == chunk.id for c in results)


def test_fts_search_excludes_non_matching_chunk(db, db_user, ready_doc):
    _make_chunk(db, ready_doc, "Gradient descent optimizes loss functions.")
    results = _fts_search("attention mechanism", db_user.id, db, limit=10)
    assert results == []


def test_fts_search_excludes_other_users_chunks(db, db_user, other_doc):
    _make_chunk(db, other_doc, "Attention is all you need.")
    results = _fts_search("attention", db_user.id, db, limit=10)
    assert results == []


def test_fts_search_excludes_non_ready_documents(db, db_user, processing_doc):
    _make_chunk(db, processing_doc, "Attention mechanism explained.")
    results = _fts_search("attention", db_user.id, db, limit=10)
    assert results == []


# ---------------------------------------------------------------------------
# retrieve — end-to-end with embed_text monkeypatched
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_embed(monkeypatch):
    vec = _unit_vector(hot_index=0)
    monkeypatch.setattr(retrieval_module, "embed_text", lambda q: vec)
    return vec


def test_retrieve_empty_db_returns_empty(db, db_user, mock_embed):
    assert retrieve("what is attention?", db_user.id, db, top_k=5) == []


def test_retrieve_returns_retrieved_chunk_instances(db, db_user, ready_doc, mock_embed):
    _make_chunk(db, ready_doc, "Self-attention explained.", embedding=_unit_vector(hot_index=0))
    results = retrieve("attention", db_user.id, db, top_k=5)
    assert all(isinstance(r, RetrievedChunk) for r in results)


def test_retrieve_includes_document_title(db, db_user, ready_doc, mock_embed):
    _make_chunk(db, ready_doc, "Self-attention explained.", embedding=_unit_vector(hot_index=0))
    results = retrieve("attention", db_user.id, db, top_k=5)
    assert any(r.document_title == "Attention Is All You Need" for r in results)


def test_retrieve_respects_top_k(db, db_user, ready_doc, mock_embed):
    for i in range(5):
        _make_chunk(db, ready_doc, f"Chunk about attention number {i}.", index=i,
                    embedding=_unit_vector(hot_index=i % 10))
    results = retrieve("attention", db_user.id, db, top_k=3)
    assert len(results) <= 3


def test_retrieve_calls_embed_text_once(db, db_user, mock_embed, monkeypatch):
    call_count = 0

    def counting_embed(q):
        nonlocal call_count
        call_count += 1
        return _unit_vector(hot_index=0)

    monkeypatch.setattr(retrieval_module, "embed_text", counting_embed)
    retrieve("test query", db_user.id, db, top_k=5)
    assert call_count == 1
