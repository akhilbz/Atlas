import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.embedding import embed_text

logger = structlog.get_logger()

# k=60 is the standard RRF constant from the original paper. It dampens the
# advantage of top-ranked results so a chunk that appears at rank 3 in one
# list doesn't completely overshadow a chunk at rank 1 in the other.
_RRF_K = 60

# Fetch more candidates than top_k from each method so RRF has enough overlap
# to rerank meaningfully. If we only fetched top_k=5, there'd be no room for
# the fusion to discover that a chunk ranked #4 in vector search is also #2 in
# FTS and should actually be the top result.
_CANDIDATES = 20


@dataclass
class RetrievedChunk:
    """A chunk returned by hybrid search, with its RRF score and source document title."""

    chunk: Chunk
    score: float
    document_title: str


def retrieve(
    query: str,
    user_id: uuid.UUID,
    db: Session,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Hybrid search: embed query, run vector + full-text search, merge with RRF.

    Returns the top_k most relevant chunks across the user's ready documents,
    each annotated with its source document title for citation display.
    """
    log = logger.bind(user_id=str(user_id), top_k=top_k)

    # Turn the query string into a 1536-d vector so we can compare it against
    # chunk embeddings stored in the DB.
    query_vector = embed_text(query)

    # Run both search strategies independently. Each returns up to _CANDIDATES
    # chunks in their own ranking order.
    vector_hits = _vector_search(query_vector, user_id, db, _CANDIDATES)
    fts_hits = _fts_search(query, user_id, db, _CANDIDATES)

    log.info("retrieval_candidates", vector=len(vector_hits), fts=len(fts_hits))

    # Merge the two ranked lists into one using RRF, then take only top_k.
    merged = _rrf_merge(vector_hits, fts_hits, top_k)

    # _rrf_merge only knows about chunks, not documents. Fetch the document
    # titles in a single query so we can attach them for citation purposes.
    doc_ids = {chunk.document_id for chunk, _ in merged}
    docs = {
        d.id: d
        for d in db.execute(select(Document).where(Document.id.in_(doc_ids))).scalars()
    }

    results = [
        RetrievedChunk(
            chunk=chunk,
            score=score,
            document_title=docs[chunk.document_id].title,
        )
        for chunk, score in merged
    ]

    log.info("retrieval_complete", returned=len(results))
    return results


def _vector_search(
    query_vector: list[float],
    user_id: uuid.UUID,
    db: Session,
    limit: int,
) -> list[Chunk]:
    """Return chunks ordered by cosine similarity to the query vector.

    Cosine similarity measures the angle between two vectors, not their
    magnitude. This means "the cat sat" and "the cat sat on the mat" will
    score similarly even though the second sentence is longer — both point
    in roughly the same semantic direction in embedding space.

    The HNSW index on chunks.embedding makes this fast even with millions of
    chunks — it's an approximate nearest-neighbour search that avoids
    comparing every single chunk.
    """
    stmt = (
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        # Only search chunks that belong to this user's documents.
        .where(Document.user_id == user_id)
        # Skip documents still being processed — their chunks may be incomplete.
        .where(Document.status == DocumentStatus.ready)
        # Chunks without embeddings haven't been processed yet; skip them.
        .where(Chunk.embedding.isnot(None))
        # <=> is pgvector's cosine distance operator (0 = identical, 2 = opposite).
        # ORDER BY distance ASC means the most similar chunk comes first.
        .order_by(Chunk.embedding.cosine_distance(query_vector))
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def _fts_search(
    query: str,
    user_id: uuid.UUID,
    db: Session,
    limit: int,
) -> list[Chunk]:
    """Return chunks matching the query via PostgreSQL full-text search.

    Full-text search excels at exact keyword matches that vector search can
    miss. For example, a query for "GPT-4" or a specific author's surname
    will reliably surface chunks that contain those exact tokens, whereas
    vector similarity might drift toward semantically related but keyword-
    different chunks.

    to_tsvector() breaks content into searchable lexemes (stems). plainto_tsquery()
    does the same for the query string. @@ checks for overlap. ts_rank() scores
    how well the chunk matches so the best matches sort first.
    """
    stmt = (
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.ready)
        # @@ is PostgreSQL's text-search match operator.
        # plainto_tsquery handles plain user input (no special syntax needed).
        .where(
            func.to_tsvector("english", Chunk.content).op("@@")(
                func.plainto_tsquery("english", query)
            )
        )
        # ts_rank scores how frequently and prominently the query terms appear.
        .order_by(
            func.ts_rank(
                func.to_tsvector("english", Chunk.content),
                func.plainto_tsquery("english", query),
            ).desc()
        )
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def _rrf_merge(
    vector_hits: list[Chunk],
    fts_hits: list[Chunk],
    top_k: int,
) -> list[tuple[Chunk, float]]:
    """Merge two ranked lists with Reciprocal Rank Fusion.

    The key insight: cosine distance and ts_rank are on completely different
    scales and can't be directly compared. RRF sidesteps this by only using
    each chunk's *rank position*, not its raw score.

    Formula: score = 1/(k + rank_in_vector) + 1/(k + rank_in_fts)

    A chunk that appears in both lists accumulates score from both terms.
    A chunk that only appears in one list gets a partial score. The merged
    list is sorted by combined score, highest first.

    Returns (chunk, rrf_score) pairs — document titles are not attached here
    because this function is kept pure (no DB access) for easier testing.
    """
    scores: dict[uuid.UUID, float] = {}
    chunks: dict[uuid.UUID, Chunk] = {}

    # enumerate(start=1) so rank 1 is the best result, not rank 0.
    # A rank-0 denominator of k+0=60 would be the same as rank 1 with k=59,
    # which is confusing — starting at 1 matches the paper's definition.
    for rank, chunk in enumerate(vector_hits, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (_RRF_K + rank)
        chunks[chunk.id] = chunk

    for rank, chunk in enumerate(fts_hits, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (_RRF_K + rank)
        chunks[chunk.id] = chunk

    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [(chunks[cid], scores[cid]) for cid in sorted_ids[:top_k]]
