"""Memory-safe helpers for importing readable and scanned PDFs.

The helpers deliberately yield one page at a time.  A textbook must never be
turned into a list of rendered images or sent to an AI provider as one prompt.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


MAX_CHARS_PER_TEXTBOOK_SECTION = 55_000
MIN_USABLE_EMBEDDED_TEXT = 80
MIN_TOPIC_SECTION_CHARACTERS = 350
# This is deliberately below the prompt size used by the AI quiz flow. A
# long textbook section can still be kept under one topic, but its saved note
# parts remain small enough to be used safely on a free hosted instance.
MAX_TOPIC_SECTION_CHARACTERS = 18_000


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


@dataclass(frozen=True)
class TopicSection:
    """A lightweight, reviewable range inside one saved study note."""

    topic: str
    start: int
    end: int


_HEADING = re.compile(
    r"(?im)^\s*((?:unit|chapter|module|lesson)\s+(?:\d+|[ivxlcdm]+|[a-z])(?:\s*[-:.]\s*|\s+)[^\n]{2,100})\s*$"
)

# The first two patterns are very reliable in copied PDFs and class handouts.
# The final title-case pattern makes ordinary headings such as "Muscle
# Structure" useful, while rejecting sentence-like lines that end in normal
# punctuation.  This deliberately does not try to infer topics from arbitrary
# prose; that would be an AI job and could split a student's ideas incorrectly.
_TOPIC_HEADING = re.compile(
    r"""(?mx)
    ^\s*(?P<title>
        (?:(?i:unit|chapter|module|lesson|section|topic)\s+
           (?:\d+(?:\.\d+)*|[ivxlcdm]+|[a-z])(?:\s*[-:.]\s*|\s+)[^\n]{2,90})
        |
        (?:\d+(?:\.\d+){1,3}\s+[A-Za-z][^\n]{2,90})
        |
        (?:[A-Z][A-Za-z0-9&/()'’\-]+(?:\s+[A-Z][A-Za-z0-9&/()'’\-]+){1,7})
    )\s*$
    """
)


def is_unreadable_ocr_error(error: Exception) -> bool:
    """Return whether OCR simply found no usable text, not a service failure."""
    message = str(error).lower()
    return (
        "could not find readable text" in message
        or "no readable text" in message
        or "no text was found" in message
    )


def is_ocr_quota_error(error: Exception) -> bool:
    """Return whether the provider temporarily refused more OCR requests."""
    message = str(error).lower()
    return "resource_exhausted" in message or "quota exceeded" in message or " 429" in message


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


def pdf_page_count_from_path(pdf_path: Path) -> int:
    """Count pages from a temporary PDF file without loading it into memory."""
    import fitz

    document = fitz.open(pdf_path)
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


def iter_pdf_pages_from_path(pdf_path: Path, first_page: int, last_page: int) -> Iterator[PdfPage]:
    """Yield current pages from a temporary file, keeping the original PDF off RAM."""
    import fitz

    document = fitz.open(pdf_path)
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


def _paragraph_ranges(text: str, start: int, end: int, maximum_size: int) -> list[tuple[int, int]]:
    """Split an oversized topic at paragraph boundaries without losing text."""
    ranges: list[tuple[int, int]] = []
    current = start
    while end - current > maximum_size:
        boundary = text.rfind("\n\n", current, current + maximum_size)
        if boundary <= current:
            boundary = text.rfind("\n", current, current + maximum_size)
        if boundary <= current:
            boundary = text.rfind(" ", current, current + maximum_size)
        if boundary <= current:
            boundary = current + maximum_size
        ranges.append((current, boundary))
        current = boundary
        while current < end and text[current].isspace():
            current += 1
    if current < end:
        ranges.append((current, end))
    return ranges


def split_study_note_topics(text: str) -> list[TopicSection]:
    """Propose topic sections from explicit headings in one note.

    The function uses no network or AI calls. It returns an empty list unless
    at least two sensible sections are found, so a chapter with only a title is
    never misleadingly split into artificial "topics".
    """
    clean_text = text.strip()
    if not clean_text:
        return []
    offset = text.find(clean_text)
    matches = [
        (" ".join(match.group("title").split()), match.start() + offset)
        for match in _TOPIC_HEADING.finditer(clean_text)
    ]
    if not matches:
        return []

    raw_sections: list[TopicSection] = []
    if matches[0][1] > offset + MIN_TOPIC_SECTION_CHARACTERS:
        raw_sections.append(TopicSection("Overview", offset, matches[0][1]))
    for index, (topic, start) in enumerate(matches):
        end = matches[index + 1][1] if index + 1 < len(matches) else offset + len(clean_text)
        raw_sections.append(TopicSection(topic, start, end))

    # A heading that only contains a caption or a cross-reference is not a
    # useful quiz boundary. Merge it into the preceding substantial section.
    sections: list[TopicSection] = []
    for candidate in raw_sections:
        if sections and candidate.end - candidate.start < MIN_TOPIC_SECTION_CHARACTERS:
            previous = sections[-1]
            sections[-1] = TopicSection(previous.topic, previous.start, candidate.end)
        else:
            sections.append(candidate)
    if len(sections) < 2:
        return []

    bounded: list[TopicSection] = []
    for section in sections:
        for start, end in _paragraph_ranges(text, section.start, section.end, MAX_TOPIC_SECTION_CHARACTERS):
            bounded.append(TopicSection(section.topic, start, end))
    return bounded
