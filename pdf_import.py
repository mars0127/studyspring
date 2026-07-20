"""Memory-safe helpers for importing readable and scanned PDFs.

The helpers deliberately yield one page at a time.  A textbook must never be
turned into a list of rendered images or sent to an AI provider as one prompt.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass


MAX_CHARS_PER_TEXTBOOK_SECTION = 55_000
MIN_USABLE_EMBEDDED_TEXT = 80


@dataclass(frozen=True)
class PdfPage:
    number: int
    text: str
    image_bytes: bytes | None


@dataclass(frozen=True)
class TextbookSection:
    title: str
    first_page: int
    last_page: int
    text: str


_HEADING = re.compile(
    r"(?im)^\s*((?:unit|chapter|module|lesson)\s+(?:\d+|[ivxlcdm]+|[a-z])(?:\s*[-:.]\s*|\s+)[^\n]{2,100})\s*$"
)


def pdf_page_count(file_bytes: bytes) -> int:
    """Return a validated page count without rendering any page."""
    import fitz

    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        if document.needs_pass:
            raise ValueError("This PDF is password-protected. Remove the password, then upload it again.")
        if not len(document):
            raise ValueError("This PDF has no pages.")
        return len(document)
    finally:
        document.close()


def iter_pdf_pages(file_bytes: bytes, first_page: int, last_page: int) -> Iterator[PdfPage]:
    """Yield one page's local text or one temporary OCR image at a time."""
    import fitz

    document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        if document.needs_pass:
            raise ValueError("This PDF is password-protected. Remove the password, then upload it again.")
        if first_page < 1 or last_page < first_page or last_page > len(document):
            raise ValueError(f"Choose pages between 1 and {len(document)}.")
        for page_number in range(first_page - 1, last_page):
            page = document.load_page(page_number)
            text = page.get_text("text").strip()
            if len(text) >= MIN_USABLE_EMBEDDED_TEXT:
                yield PdfPage(page_number + 1, text, None)
                continue
            # Low resolution is sufficient for printed textbook text and keeps each
            # request small. The pixmap is released before the next page is rendered.
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
            try:
                yield PdfPage(page_number + 1, text, pixmap.tobytes("png"))
            finally:
                del pixmap
    finally:
        document.close()


def section_title_from_text(text: str) -> str | None:
    """Find a likely unit/chapter heading at the start of a page."""
    match = _HEADING.search(text[:1_500])
    return " ".join(match.group(1).split()) if match else None


def split_textbook_sections(pages: list[tuple[int, str]]) -> list[TextbookSection]:
    """Split extracted textbook pages at headings, with a safe size fallback."""
    sections: list[TextbookSection] = []
    current: list[str] = []
    first_page: int | None = None
    last_page: int | None = None
    title: str | None = None

    def finish() -> None:
        nonlocal current, first_page, last_page, title
        if current and first_page is not None and last_page is not None:
            sections.append(
                TextbookSection(
                    title=title or f"Textbook pages {first_page}-{last_page}",
                    first_page=first_page,
                    last_page=last_page,
                    text="\n\n".join(current).strip(),
                )
            )
        current, first_page, last_page, title = [], None, None, None

    for page_number, page_text in pages:
        heading = section_title_from_text(page_text)
        current_size = sum(len(part) for part in current)
        if current and (heading or current_size + len(page_text) > MAX_CHARS_PER_TEXTBOOK_SECTION):
            finish()
        if first_page is None:
            first_page = page_number
            title = heading
        last_page = page_number
        current.append(f"[Page {page_number}]\n{page_text}")
    finish()
    return sections
