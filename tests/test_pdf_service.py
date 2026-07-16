"""Checks for PDF validation and memory-safe page selection."""

from io import BytesIO
import unittest

from pypdf import PdfWriter

from services.pdf_service import (
    MAX_PROCESSING_PAGES,
    PdfImportError,
    inspect_pdf,
    validate_page_range,
    validate_pdf_upload,
)
import database
from pathlib import Path
import tempfile
from services.textbook_import_service import start_textbook_import


def blank_pdf(page_count: int = 1) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return output.getvalue()


class PdfServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temporary_directory.name) / "test.db"
        database.initialize_database()

    def tearDown(self) -> None:
        database.DATABASE_PATH = self.original_path
        self.temporary_directory.cleanup()

    def test_invalid_extension_and_damaged_input_are_rejected(self) -> None:
        with self.assertRaises(PdfImportError):
            validate_pdf_upload("notes.txt", b"%PDF-1.4", 30)
        with self.assertRaises(PdfImportError):
            validate_pdf_upload("notes.pdf", b"not-a-pdf", 30)

    def test_encrypted_pdf_is_rejected(self) -> None:
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("secret")
        writer.write(output)
        with self.assertRaises(PdfImportError):
            validate_pdf_upload("locked.pdf", output.getvalue(), 30)

    def test_inspection_identifies_a_scanned_style_pdf(self) -> None:
        inspection = inspect_pdf("scan.pdf", blank_pdf(3))
        self.assertEqual(inspection.page_count, 3)
        self.assertEqual(inspection.document_kind, "scanned")
        self.assertEqual(len(inspection.document_hash), 64)

    def test_page_range_has_a_fixed_safe_limit(self) -> None:
        validate_page_range(1, MAX_PROCESSING_PAGES, MAX_PROCESSING_PAGES)
        with self.assertRaises(PdfImportError):
            validate_page_range(1, MAX_PROCESSING_PAGES + 1, MAX_PROCESSING_PAGES + 1)
        with self.assertRaises(PdfImportError):
            validate_page_range(4, 3, 10)

    def test_entire_textbook_creates_one_checkpoint_job(self) -> None:
        course_id = database.create_course("Functions", "Math", None)
        job_id, pages = start_textbook_import(course_id=course_id, filename="book.pdf", pdf_bytes=blank_pdf(22))
        self.assertEqual(pages, 22)
        self.assertEqual(len(database.list_pdf_import_pages(job_id)), 22)


if __name__ == "__main__":
    unittest.main()
