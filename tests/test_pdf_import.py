"""Tests for bounded textbook-section behaviour."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    import fitz
except ImportError:  # The lightweight test runner may not have optional PDF rendering installed.
    fitz = None

from pdf_import import (
    MAX_CHARS_PER_TEXTBOOK_SECTION,
    is_ocr_quota_error,
    is_unreadable_ocr_error,
    iter_pdf_pages,
    iter_pdf_pages_from_path,
    pdf_page_count,
    pdf_page_count_from_path,
    split_study_note_topics,
    split_textbook_sections,
)


class TextbookSectionTests(unittest.TestCase):
    def test_unreadable_ocr_errors_can_be_skipped(self) -> None:
        self.assertTrue(is_unreadable_ocr_error(ValueError("Gemini could not find readable text in that image.")))
        self.assertFalse(is_unreadable_ocr_error(RuntimeError("429 RESOURCE_EXHAUSTED")))

    def test_quota_errors_pause_further_ocr_requests(self) -> None:
        self.assertTrue(is_ocr_quota_error(RuntimeError("429 RESOURCE_EXHAUSTED")))
        self.assertFalse(is_ocr_quota_error(ValueError("No readable text was found")))

    @unittest.skipIf(fitz is None, "PyMuPDF is not installed in this test environment")
    def test_digital_pdf_uses_embedded_text_without_an_image(self) -> None:
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "This is enough selectable textbook text to use local extraction without OCR. " * 2)
        pdf_bytes = document.tobytes()
        document.close()

        pages = list(iter_pdf_pages(pdf_bytes, 1, 1))

        self.assertEqual(pdf_page_count(pdf_bytes), 1)
        self.assertIn("selectable textbook text", pages[0].text)
        self.assertIsNone(pages[0].image_bytes)

    @unittest.skipIf(fitz is None, "PyMuPDF is not installed in this test environment")
    def test_digital_pdf_can_be_read_from_a_temporary_file(self) -> None:
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Temporary-file PDF extraction keeps the original PDF out of scan memory. " * 2)
        with TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "notes.pdf"
            document.save(pdf_path)
            pages = list(iter_pdf_pages_from_path(pdf_path, 1, 1))
            self.assertEqual(pdf_page_count_from_path(pdf_path), 1)
            self.assertIsNone(pages[0].image_bytes)
        document.close()

    def test_splits_at_a_chapter_heading(self) -> None:
        sections = split_textbook_sections(
            [
                (1, "Introduction to functions"),
                (2, "Chapter 1: Functions\nA function assigns one output."),
                (3, "More about domain and range."),
            ]
        )

        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[1].title, "Chapter 1: Functions")
        self.assertEqual(sections[1].first_page, 2)

    def test_splits_large_text_even_without_headings(self) -> None:
        sections = split_textbook_sections(
            [(1, "a" * (MAX_CHARS_PER_TEXTBOOK_SECTION - 10)), (2, "b" * 50)]
        )

        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].last_page, 1)
        self.assertEqual(sections[1].first_page, 2)

    def test_note_topics_use_real_subheadings_and_keep_short_references_together(self) -> None:
        text = (
            "Chapter 4: Muscles\n" + "A" * 800
            + "\n\n4.1 Muscle Naming\n" + "B" * 800
            + "\n\n4.2 Muscle Structure\n" + "C" * 800
            + "\n\n4.3 Muscle Contractions\n" + "D" * 800
        )

        sections = split_study_note_topics(text)

        self.assertEqual([section.topic for section in sections], [
            "Chapter 4: Muscles",
            "4.1 Muscle Naming",
            "4.2 Muscle Structure",
            "4.3 Muscle Contractions",
        ])
        self.assertEqual("".join(text[section.start:section.end] for section in sections), text)

    def test_note_topics_do_not_split_plain_prose_without_headings(self) -> None:
        self.assertEqual(
            split_study_note_topics("Muscle structure helps movement. " * 100), []
        )


if __name__ == "__main__":
    unittest.main()
