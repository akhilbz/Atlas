import structlog
from openai import OpenAI, OpenAIError

from app.config import get_settings
from app.utils.chunking import TextChunk

logger = structlog.get_logger()

_MODEL = "text-embedding-3-small"
_DIMENSIONS = 1536
_BATCH_SIZE = 100  # well under the API limit; easier to test and safer under rate limits


def embed_chunks(chunks: list[TextChunk]) -> list[list[float]]:
    """Return one embedding vector per chunk, preserving input order.

    Returns an empty list immediately when given no chunks — no API call is made.
    """
    if not chunks:
        return []
    texts = [chunk.content for chunk in chunks]
    return _embed_texts(texts)


def embed_text(text: str) -> list[float]:
    """Embed a single string and return its vector.

    Used at query time to embed the user's question before nearest-neighbour search.
    """
    return _embed_texts([text])[0]


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Call the OpenAI embeddings API in batches of _BATCH_SIZE.

    Sorts each batch response by the returned index field so order is guaranteed
    even if the API ever returns items out of sequence.
    Raises RuntimeError on any OpenAI API failure so callers get a clean error type.
    """
    client = _make_client()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        try:
            response = client.embeddings.create(model=_MODEL, input=batch)
        except OpenAIError as exc:
            raise RuntimeError(f"Embedding API error: {exc}") from exc

        sorted_data = sorted(response.data, key=lambda d: d.index)
        all_embeddings.extend(d.embedding for d in sorted_data)

        logger.debug(
            "embeddings_created",
            batch_start=i,
            batch_size=len(batch),
            model=_MODEL,
        )

    return all_embeddings


def _make_client() -> OpenAI:
    """Instantiate an OpenAI client. Isolated function so tests can monkeypatch it."""
    return OpenAI(api_key=get_settings().openai_api_key)
