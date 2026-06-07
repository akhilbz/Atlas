from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Annotated[Session, Depends(get_db)]) -> JSONResponse:
    """Return service health. Checks database connectivity via get_db so tests can override it."""
    try:
        db.execute(text("SELECT 1"))
        return JSONResponse(content={"status": "ok", "db": "ok"})
    except Exception:
        logger.exception("database_health_check_failed")
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "error"})
