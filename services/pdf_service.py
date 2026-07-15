"""Memory-conscious PDF validation, inspection, and page extraction."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from io import BytesIO
from typing import Iterator

from pypdf import PdfReader


def _setting(name: str, default: int) -> int:
    """Read a positive integer deployment setting without breaking startup."""
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        return default


STANDARD_PDF_MAX_MB = _setting("STANDARD_PDF_MAX_MB", 30)
TEXTBOOK_PDF_MAX_MB = _setting("TEXTBOOK_PDF_MAX_MB", 200)
MAX_PROCESSING_PAGES = _setting("PDF_MAX_PROCESSING_PAGES", 20)
RENDER_BATCH_SIZE = _setting("PDF_RENDER_BATCH_SIZE", 5)
MIN_READABLE_TEXT_CHARACTERS = 40


class PdfImportError(ValueError):
    """A safe, student-readable PDF import failure."""


@dataclass(frozen=True)
class PdfInspection:
    document_hash: str
    file_size_bytes: int
    page_count: int
    readable_sample_pages: int
    sampled_pages: int
    document_kind: str

    @property
    def readable_text_percentage(self) -> int:
        if not self.sampled_pages:
            return 0
        return round(self.readable_sample_pages / self.sampled_pages * 100)


def _max_bytes(max_mb: int) -> int:
    return max_mb * 1024 * 1024


def validate_pdf_upload(filename: str, file_bytes: bytes, max_mb: int) -> None:
    """Reject unsupported, oversized, encrypted, or malformed PDFs early."""
    if not filename.lower().endswith(".pdf"):
        raise PdfImportError("Choose a PDF file.")
    if not file_bytes:
        raise PdfImportError("The uploaded file is empty.")
    if len(file_bytes) > _max_bytes(max_mb):
        raise PdfImportError(f"This file is larger than the {max_mb} MB limit for this import.")
    if not file_bytes.startswith(b"%PDF-"):
        raise PdfImportError("This file is not a valid PDF.")
    try:
        reader = PdfReader(BytesIO(file_bytes), strict=False)
        if reader.is_encrypted:
            raise PdfImportError("This PDF is password-protected. Remove the password before importing it.")
        if not reader.pages:
            raise PdfImportError("This PDF has no pages to import.")
    except PdfImportError:
        raise
    except Exception as error:
        raise PdfImportError("StudySpring could not open this PDF. It may be damaged or unsupported.") from error


def inspect_pdf(filename: str, file_bytes: bytes, max_mb: int = TEXTBOOK_PDF_MAX_MB) -> PdfInspection:
    """Inspect a few evenly distributed pages without rendering the whole document."""
    validate_pdf_upload(filename, file_bytes, max_mb)
    reader = PdfReader(BytesIO(file_bytes), strict=False)
    page_count = len(reader.pages)
    sample_indexes = sorted({round(index * (page_count - 1) / min(4, page_count - 1)) for index in range(min(5, page_count))}) if page_count > 1 else [0]
    readable = 0
    for index in sample_indexes:
        try:
            if len((reader.pages[index].extract_text() or "").strip()) >= MIN_READABLE_TEXT_CHARACTERS:
                readable += 1
        except Exception:
            continue
    if readable == len(sample_indexes):
        kind = "text-readable"
    elif readable == 0:
        kind = "scanned"
    else:
        kind = "mixed"
    return PdfInspection(
        document_hash=hashlib.sha256(file_bytes).hexdigest(),
        file_size_bytes=len(file_bytes),
        page_count=page_count,
        readable_sample_pages=readable,
        sampled_pages=len(sample_indexes),
        document_kind=kind,
    )


def validate_page_range(first_page: int, last_page: int, page_count: int) -> None:
    if first_page < 1 or last_page < first_page:
        raise PdfImportError("Choose a valid starting and ending page.")
    if last_page > page_count:
        raise PdfImportError(f"This PDF has {page_count} page(s). Choose a smaller ending page.")
    if last_page - first_page + 1 > MAX_PROCESSING_PAGES:
        raise PdfImportError(f"Choose no more than {MAX_PROCESSING_PAGES} pages at a time.")


def extract_embedded_text(file_bytes: bytes, first_page: int, last_page: int) -> Iterator[tuple[int, str]]:
    """Yield embedded text one page at a time, releasing each page before the next."""
    reader = PdfReader(BytesIO(file_bytes), strict=False)
    validate_page_range(first_page, last_page, len(reader.pages))
    for page_number in range(first_page, last_page + 1):
        try:
            text = (reader.pages[page_number - 1].extract_text() or "").strip()
        except Exception:
            text = ""
        yield page_number, text


def render_page_png(file_bytes: bytes, page_number: int) -> bytes:
    """Render exactly one page for OCR; never retain a document-wide image list."""
    try:
        import fitz
    except ImportError as error:
        raise PdfImportError("Scanned-PDF support is not installed on this server.") from error
    try:
        document = fitz.open(stream=file_bytes, filetype="pdf")
        if page_number < 1 or page_number > len(document):
            raise PdfImportError(f"This PDF has {len(document)} page(s). Choose a valid page.")
        page = document.load_page(page_number - 1)
        return page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False).tobytes("png")
    except PdfImportError:
        raise
    except Exception as error:
        raise PdfImportError("StudySpring could not render that PDF page.") from error
    finally:
        if "document" in locals():
            document.close()
