"""Tests for bounded textbook-section behaviour."""

import unittest

try:
    import fitz
except ImportError:  # The lightweight test runner may not have optional PDF rendering installed.
    fitz = None

from pdf_import import (
    MAX_CHARS_PER_TEXTBOOK_SECTION,
    is_unreadable_ocr_error,
    iter_pdf_pages,
    pdf_page_count,
    split_textbook_sections,
)


class TextbookSectionTests(unittest.TestCase):
    def test_unreadable_ocr_errors_can_be_skipped(self) -> None:
        self.assertTrue(is_unreadable_ocr_error(ValueError("Gemini could not find readable text in that image.")))
        self.assertFalse(is_unreadable_ocr_error(RuntimeError("429 RESOURCE_EXHAUSTED")))

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


if __name__ == "__main__":
    unittest.main()
