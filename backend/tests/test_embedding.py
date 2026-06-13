"""
Unit tests for services/embedding.py.

All OpenAI API calls are intercepted via monkeypatch — no real network requests
and no API key required. Tests operate on the service functions directly.
"""

import pytest
from unittest.mock import MagicMock
from openai import OpenAIError

import app.services.embedding as emb
from app.services.embedding import embed_chunks, embed_text, _DIMENSIONS, _BATCH_SIZE, _MODEL
from app.utils.chunking import TextChunk


# ---------------------------------------------------------------------------
# Helpers — build mock OpenAI responses
# ---------------------------------------------------------------------------

def _make_embedding_object(index: int, value: float | None = None) -> MagicMock:
    """Fake embedding object matching the shape of openai.types.Embedding."""
    obj = MagicMock()
    obj.index = index
    obj.embedding = [value if value is not None else float(index)] * _DIMENSIONS
    return obj


def _make_response(n: int, values: list[float] | None = None) -> MagicMock:
    """Fake CreateEmbeddingResponse for n texts."""
    response = MagicMock()
    response.data = [
        _make_embedding_object(i, values[i] if values else None)
        for i in range(n)
    ]
    return response


def _make_chunk(index: int, content: str | None = None) -> TextChunk:
    return TextChunk(
        content=content or f"Sentence number {index}.",
        chunk_index=index,
        token_count=5,
    )


# ---------------------------------------------------------------------------
# Fixture — patches _make_client so no real OpenAI client is ever created
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_client(monkeypatch):
    """Return a MagicMock OpenAI client wired into the embedding service."""
    client = MagicMock()
    monkeypatch.setattr(emb, "_make_client", lambda: client)
    return client


# ---------------------------------------------------------------------------
# embed_chunks — basic behaviour
# ---------------------------------------------------------------------------

def test_embed_chunks_empty_input_returns_empty_list(mock_client):
    assert embed_chunks([]) == []


def test_embed_chunks_empty_input_makes_no_api_call(mock_client):
    embed_chunks([])
    mock_client.embeddings.create.assert_not_called()


def test_embed_chunks_returns_one_vector_per_chunk(mock_client):
    chunks = [_make_chunk(i) for i in range(4)]
    mock_client.embeddings.create.return_value = _make_response(4)
    result = embed_chunks(chunks)
    assert len(result) == 4


def test_embed_chunks_vectors_have_correct_dimensionality(mock_client):
    chunks = [_make_chunk(0)]
    mock_client.embeddings.create.return_value = _make_response(1)
    result = embed_chunks(chunks)
    assert len(result[0]) == _DIMENSIONS


def test_embed_chunks_vectors_contain_floats(mock_client):
    chunks = [_make_chunk(0)]
    mock_client.embeddings.create.return_value = _make_response(1)
    result = embed_chunks(chunks)
    assert all(isinstance(v, float) for v in result[0])


def test_embed_chunks_uses_correct_model(mock_client):
    chunks = [_make_chunk(0)]
    mock_client.embeddings.create.return_value = _make_response(1)
    embed_chunks(chunks)
    call_kwargs = mock_client.embeddings.create.call_args.kwargs
    assert call_kwargs["model"] == _MODEL


def test_embed_chunks_passes_chunk_content_as_input(mock_client):
    chunks = [
        _make_chunk(0, "First sentence."),
        _make_chunk(1, "Second sentence."),
    ]
    mock_client.embeddings.create.return_value = _make_response(2)
    embed_chunks(chunks)
    call_kwargs = mock_client.embeddings.create.call_args.kwargs
    assert call_kwargs["input"] == ["First sentence.", "Second sentence."]


# ---------------------------------------------------------------------------
# embed_chunks — batching
# ---------------------------------------------------------------------------

def test_embed_chunks_single_batch_for_small_input(mock_client):
    chunks = [_make_chunk(i) for i in range(10)]
    mock_client.embeddings.create.return_value = _make_response(10)
    embed_chunks(chunks)
    assert mock_client.embeddings.create.call_count == 1


def test_embed_chunks_splits_into_multiple_batches(mock_client):
    """_BATCH_SIZE + 1 chunks must trigger exactly 2 API calls."""
    n = _BATCH_SIZE + 1
    chunks = [_make_chunk(i) for i in range(n)]
    mock_client.embeddings.create.side_effect = [
        _make_response(_BATCH_SIZE),
        _make_response(1),
    ]
    result = embed_chunks(chunks)
    assert mock_client.embeddings.create.call_count == 2
    assert len(result) == n


def test_embed_chunks_preserves_order_across_batches(mock_client):
    """Vectors must come back in the same order as the input chunks."""
    n = _BATCH_SIZE + 5
    chunks = [_make_chunk(i) for i in range(n)]
    # Give each chunk a unique float value so we can verify ordering
    first_batch_values = [float(i) for i in range(_BATCH_SIZE)]
    second_batch_values = [float(i + _BATCH_SIZE) for i in range(5)]
    mock_client.embeddings.create.side_effect = [
        _make_response(_BATCH_SIZE, first_batch_values),
        _make_response(5, second_batch_values),
    ]
    result = embed_chunks(chunks)
    assert result[0][0] == 0.0
    assert result[_BATCH_SIZE][0] == float(_BATCH_SIZE)


# ---------------------------------------------------------------------------
# embed_chunks — error handling
# ---------------------------------------------------------------------------

def test_embed_chunks_openai_error_raises_runtime_error(mock_client):
    mock_client.embeddings.create.side_effect = OpenAIError("rate limit exceeded")
    with pytest.raises(RuntimeError, match="Embedding API error"):
        embed_chunks([_make_chunk(0)])


# ---------------------------------------------------------------------------
# embed_text
# ---------------------------------------------------------------------------

def test_embed_text_returns_a_list(mock_client):
    mock_client.embeddings.create.return_value = _make_response(1)
    result = embed_text("What is the methodology?")
    assert isinstance(result, list)


def test_embed_text_returns_correct_dimensionality(mock_client):
    mock_client.embeddings.create.return_value = _make_response(1)
    result = embed_text("What is the methodology?")
    assert len(result) == _DIMENSIONS


def test_embed_text_makes_exactly_one_api_call(mock_client):
    mock_client.embeddings.create.return_value = _make_response(1)
    embed_text("A query string.")
    assert mock_client.embeddings.create.call_count == 1


def test_embed_text_passes_string_directly_as_input(mock_client):
    mock_client.embeddings.create.return_value = _make_response(1)
    embed_text("My query.")
    call_kwargs = mock_client.embeddings.create.call_args.kwargs
    assert call_kwargs["input"] == ["My query."]
