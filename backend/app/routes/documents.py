import uuid
from pathlib import Path
from typing import Annotated

import structlog
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.models.document import Document, DocumentStatus, SourceType
from app.schemas.document import DocumentResponse
from app.services.auth import CurrentUserDep, DbDep

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

    logger.info(
        "document_uploaded",
        document_id=str(document.id),
        file_type=suffix,
        user_id=str(current_user.id),
        status=document.status,
    )
    return DocumentResponse.model_validate(document)
