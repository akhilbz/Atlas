import base64
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import structlog
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, or_, select

from app.config import get_settings
from app.models.document import Document, DocumentStatus, SourceType
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.services.auth import CurrentUserDep, DbDep
from app.tasks.embedding import process_document

logger = structlog.get_logger()

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}


def _max_bytes() -> int:
    return get_settings().max_upload_size_mb * 1024 * 1024


def _upload_dir() -> Path:
    path = get_settings().upload_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_document(
    file: Annotated[UploadFile, File()],
    current_user: CurrentUserDep,
    db: DbDep,
) -> DocumentResponse:
    """Accept a PDF, TXT, or MD file upload. TXT/MD are processed inline; PDFs are queued for background processing."""
    suffix = Path(file.filename or "").suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File type '{suffix}' is not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    contents = file.file.read()

    if len(contents) > _max_bytes():
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size {len(contents) / 1024 / 1024:.1f}MB exceeds the {get_settings().max_upload_size_mb}MB limit",
        )

    title = Path(file.filename or "untitled").stem

    if suffix == ".pdf":
        file_id = uuid.uuid4()
        dest = _upload_dir() / f"{file_id}.pdf"
        dest.write_bytes(contents)

        document = Document(
            user_id=current_user.id,
            title=title,
            source_type=SourceType.upload,
            file_path=str(dest),
            status=DocumentStatus.processing,
        )
    else:
        try:
            text = contents.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="File could not be read as UTF-8 text",
            )

        document = Document(
            user_id=current_user.id,
            title=title,
            content=text,
            source_type=SourceType.upload,
            status=DocumentStatus.ready,
        )

    db.add(document)
    db.commit()
    db.refresh(document)

    if suffix == ".pdf":
        process_document.delay(str(document.id))

    logger.info(
        "document_uploaded",
        document_id=str(document.id),
        file_type=suffix,
        user_id=str(current_user.id),
        status=document.status,
    )
    return DocumentResponse.model_validate(document)


# ---------------------------------------------------------------------------
# Library endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=DocumentListResponse)
def list_documents(
    current_user: CurrentUserDep,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> DocumentListResponse:
    """Return a cursor-paginated list of the authenticated user's documents, newest first."""
    query = (
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit + 1)
    )

    if cursor:
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        query = query.where(
            or_(
                Document.created_at < cursor_created_at,
                and_(
                    Document.created_at == cursor_created_at,
                    Document.id < cursor_id,
                ),
            )
        )

    rows = db.execute(query).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = _encode_cursor(items[-1]) if has_more else None

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(doc) for doc in items],
        next_cursor=next_cursor,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: uuid.UUID,
    current_user: CurrentUserDep,
    db: DbDep,
) -> DocumentResponse:
    """Return a single document. 404 if not found or owned by another user."""
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentResponse.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    current_user: CurrentUserDep,
    db: DbDep,
) -> None:
    """Delete a document and its chunks. 404 if not found or owned by another user."""
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    db.delete(doc)
    db.commit()
    logger.info("document_deleted", document_id=str(document_id), user_id=str(current_user.id))


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------

def _encode_cursor(doc: Document) -> str:
    """Encode a document's position as an opaque base64 cursor string."""
    payload = {"id": str(doc.id), "created_at": doc.created_at.isoformat()}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode a cursor string back to (created_at, id). Raises 400 on invalid input."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["created_at"]), uuid.UUID(payload["id"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")
