import uuid
from pathlib import Path

import structlog

from app.database import SessionLocal
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.embedding import embed_chunks
from app.utils.chunking import chunk_text
from app.utils.pdf import extract_text_from_pdf
from app.worker import celery_app

logger = structlog.get_logger()


@celery_app.task(name="tasks.process_document")
def process_document(document_id: str) -> None:
    """Celery entry point — delegates to _do_process_document."""
    _do_process_document(document_id)


def _do_process_document(document_id: str) -> None:
    """Extract, chunk, embed, and store a document's chunks.

    Separated from the Celery decorator so it can be called directly in tests.
    Updates Document.status to 'ready' on success, 'failed' on any error.
    """
    log = logger.bind(document_id=document_id)
    log.info("process_document_started")

    db = SessionLocal()
    doc = None
    try:
        doc = db.get(Document, uuid.UUID(document_id))

        if doc is None:
            log.warning("document_not_found")
            return

        if doc.status == DocumentStatus.ready:
            log.info("document_already_ready_skipping")
            return

        # --- Extract text ---
        if doc.file_path:
            text = extract_text_from_pdf(Path(doc.file_path))
            doc.content = text  # cache on the record for full-text search
        else:
            text = doc.content or ""

        if not text.strip():
            log.warning("document_has_no_extractable_text")
            doc.status = DocumentStatus.failed
            db.commit()
            return

        # --- Chunk ---
        chunks = chunk_text(text)
        log.info("document_chunked", num_chunks=len(chunks))

        # --- Embed ---
        vectors = embed_chunks(chunks)

        # --- Persist ---
        chunk_records = [
            Chunk(
                document_id=doc.id,
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                token_count=chunk.token_count,
                embedding=vector,
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        db.add_all(chunk_records)
        doc.status = DocumentStatus.ready
        db.commit()

        log.info("process_document_complete", num_chunks=len(chunk_records))

    except Exception as exc:
        db.rollback()
        log.error("process_document_failed", error=str(exc))
        if doc is not None:
            try:
                doc.status = DocumentStatus.failed
                db.commit()
            except Exception:
                db.rollback()
    finally:
        db.close()
