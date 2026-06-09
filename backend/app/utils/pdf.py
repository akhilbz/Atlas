import re
from pathlib import Path

import fitz  # PyMuPDF
import structlog

logger = structlog.get_logger()


def extract_text_from_pdf(file_path: Path) -> str:
    """Extract and return all text from a PDF file.

    Returns an empty string for PDFs with no text layer (scanned images).
    Raises ValueError for corrupted or password-protected files.
    """
    try:
        doc = fitz.open(file_path)
    except Exception as exc:
        raise ValueError(f"Could not open PDF: {exc}") from exc

    if doc.needs_pass:
        doc.close()
        raise ValueError("PDF is password-protected and cannot be processed")

    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text())

    doc.close()

    raw = "\n".join(pages)
    return _clean_whitespace(raw)


def _clean_whitespace(text: str) -> str:
    """Collapse runs of blank lines and strip leading/trailing whitespace."""
    # Collapse 3+ consecutive newlines down to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
