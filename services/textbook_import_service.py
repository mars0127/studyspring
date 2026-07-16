"""Checkpointed, bounded textbook extraction for the Imports destination."""

from __future__ import annotations

from collections.abc import Callable

from database import (
    complete_pdf_import_job,
    create_or_resume_pdf_import_job,
    list_pdf_import_pages,
    save_pdf_import_page,
)
from gemini_client import GeminiRequestError, create_gemini_client, extract_text_from_image
from services.pdf_service import (
    MIN_READABLE_TEXT_CHARACTERS,
    PdfImportError,
    extract_embedded_text,
    inspect_pdf,
    render_page_png,
    validate_page_range,
)


ProgressCallback = Callable[[int, int, str], None]


def process_textbook_range(
    *, course_id: int, filename: str, pdf_bytes: bytes, first_page: int,
    last_page: int, api_key: str | None, progress: ProgressCallback | None = None,
) -> tuple[list[str], list[int]]:
    """Save each selected page immediately; OCR only pages without usable PDF text."""
    inspection = inspect_pdf(filename, pdf_bytes)
    validate_page_range(first_page, last_page, inspection.page_count)
    job_id = create_or_resume_pdf_import_job(
        course_id, inspection.document_hash, filename, first_page, last_page
    )
    saved_pages = {page["page_number"]: page for page in list_pdf_import_pages(job_id)}
    client = create_gemini_client(api_key) if api_key else None
    completed, failed = [], []
    total = last_page - first_page + 1
    for position, (page_number, embedded_text) in enumerate(
        extract_embedded_text(pdf_bytes, first_page, last_page), start=1
    ):
        existing = saved_pages.get(page_number, {})
        if existing.get("status") == "completed":
            completed.append(str(existing.get("extracted_text", "")))
            continue
        if progress:
            progress(position - 1, total, f"Reading page {page_number} of {last_page}…")
        try:
            if len(embedded_text) >= MIN_READABLE_TEXT_CHARACTERS:
                text, method = embedded_text, "embedded_text"
            else:
                if not api_key:
                    raise PdfImportError(
                        "This page is a scan. Ask the site owner to enable the optional private AI reader, or upload an OCR-readable copy."
                    )
                image = render_page_png(pdf_bytes, page_number)
                text = extract_text_from_image(api_key, image, "image/png", client=client)
                method = "gemini_ocr"
            save_pdf_import_page(job_id, page_number, "completed", method, text)
            completed.append(text)
        except Exception as error:
            save_pdf_import_page(job_id, page_number, "failed", error_message=str(error))
            failed.append(page_number)
            if isinstance(error, GeminiRequestError):
                break
    complete_pdf_import_job(job_id)
    if progress:
        progress(total, total, "Selected pages saved.")
    return completed, failed


def start_textbook_import(
    *, course_id: int, filename: str, pdf_bytes: bytes,
) -> tuple[int, int]:
    """Create one whole-book checkpoint job without processing its pages yet."""
    inspection = inspect_pdf(filename, pdf_bytes)
    job_id = create_or_resume_pdf_import_job(
        course_id, inspection.document_hash, filename, 1, inspection.page_count
    )
    return job_id, inspection.page_count


def process_next_textbook_batch(
    *, job_id: int, pdf_bytes: bytes, api_key: str | None,
    progress: ProgressCallback | None = None,
) -> tuple[list[str], list[int], bool]:
    """Process one bounded internal batch from a whole-book checkpoint job."""
    pages = list_pdf_import_pages(job_id)
    pending = [int(page["page_number"]) for page in pages if page["status"] == "pending"]
    if not pending:
        complete_pdf_import_job(job_id)
        return [], [], True
    selected = pending[:20]
    # A job creates pages in order, so this is always a small contiguous extraction window.
    first_page, last_page = selected[0], selected[-1]
    client = create_gemini_client(api_key) if api_key else None
    completed, failed = [], []
    for position, (page_number, embedded_text) in enumerate(
        extract_embedded_text(pdf_bytes, first_page, last_page), start=1
    ):
        if progress:
            progress(position - 1, len(selected), f"Reading page {page_number}…")
        try:
            if len(embedded_text) >= MIN_READABLE_TEXT_CHARACTERS:
                text, method = embedded_text, "embedded_text"
            else:
                if not api_key:
                    raise PdfImportError("This page is a scan. Enable the optional private AI reader or upload an OCR-readable copy.")
                image = render_page_png(pdf_bytes, page_number)
                text, method = extract_text_from_image(api_key, image, "image/png", client=client), "gemini_ocr"
            save_pdf_import_page(job_id, page_number, "completed", method, text)
            completed.append(text)
        except Exception as error:
            save_pdf_import_page(job_id, page_number, "failed", error_message=str(error))
            failed.append(page_number)
            if isinstance(error, GeminiRequestError):
                break
    complete_pdf_import_job(job_id)
    remaining = any(page["status"] == "pending" for page in list_pdf_import_pages(job_id))
    if progress:
        progress(len(selected), len(selected), "Batch saved.")
    return completed, failed, not remaining
