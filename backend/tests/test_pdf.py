"""
Unit tests for utils/pdf.py.

PDFs are created in-memory using PyMuPDF itself so no fixture files are needed.
All tests operate on the utility function directly — no HTTP, no database.
"""

import pytest
import fitz
from pathlib import Path

from app.utils.pdf import extract_text_from_pdf


# ---------------------------------------------------------------------------
# Helpers — build PDFs in memory and write to tmp files
# ---------------------------------------------------------------------------

def _make_pdf(tmp_path: Path, pages: list[str], password: str = "") -> Path:
    """Create a PDF with one text block per page and return its path."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=12)
    dest = tmp_path / "test.pdf"
    if password:
        doc.save(str(dest), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password)
    else:
        doc.save(str(dest))
    doc.close()
    return dest


def _make_scanned_pdf(tmp_path: Path) -> Path:
    """Create a PDF with a page but no text layer (simulates a scanned image PDF)."""
    doc = fitz.open()
    doc.new_page()   # page exists but no text inserted
    dest = tmp_path / "scanned.pdf"
    doc.save(str(dest))
    doc.close()
    return dest


# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------

def test_extracts_text_from_single_page(tmp_path):
    path = _make_pdf(tmp_path, ["Hello world. This is page one."])
    result = extract_text_from_pdf(path)
    assert "Hello world" in result


def test_extracts_text_from_multiple_pages(tmp_path):
    path = _make_pdf(tmp_path, ["Page one content.", "Page two content.", "Page three content."])
    result = extract_text_from_pdf(path)
    assert "Page one content" in result
    assert "Page two content" in result
    assert "Page three content" in result


def test_returns_string(tmp_path):
    path = _make_pdf(tmp_path, ["Some content."])
    result = extract_text_from_pdf(path)
    assert isinstance(result, str)


def test_result_is_stripped(tmp_path):
    path = _make_pdf(tmp_path, ["Content with surrounding whitespace."])
    result = extract_text_from_pdf(path)
    assert result == result.strip()


def test_no_excessive_blank_lines(tmp_path):
    path = _make_pdf(tmp_path, ["First paragraph.", "Second paragraph."])
    result = extract_text_from_pdf(path)
    assert "\n\n\n" not in result


# ---------------------------------------------------------------------------
# Edge cases — empty and scanned PDFs
# ---------------------------------------------------------------------------

def test_scanned_pdf_returns_empty_string(tmp_path):
    """A PDF with pages but no text layer returns empty string — OCR is out of scope."""
    path = _make_scanned_pdf(tmp_path)
    result = extract_text_from_pdf(path)
    assert result == ""


def test_single_page_with_multiple_lines(tmp_path):
    long_text = "\n".join(f"Line {i}" for i in range(20))
    path = _make_pdf(tmp_path, [long_text])
    result = extract_text_from_pdf(path)
    assert "Line 0" in result
    assert "Line 19" in result


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_corrupted_file_raises_value_error(tmp_path):
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"this is not a pdf at all %%EOF garbage")
    with pytest.raises(ValueError, match="Could not open PDF"):
        extract_text_from_pdf(bad)


def test_nonexistent_file_raises_value_error(tmp_path):
    missing = tmp_path / "ghost.pdf"
    with pytest.raises(ValueError, match="Could not open PDF"):
        extract_text_from_pdf(missing)


def test_password_protected_raises_value_error(tmp_path):
    path = _make_pdf(tmp_path, ["Secret content."], password="secret123")
    with pytest.raises(ValueError, match="password-protected"):
        extract_text_from_pdf(path)
