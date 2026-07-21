"""Tests for safely accepting Gemini quiz output."""

import unittest

from gemini_client import _semantic_sections, parse_questions, plan_question_batches, split_question_source


class GeminiClientTests(unittest.TestCase):
    def test_parse_questions_keeps_valid_question(self) -> None:
        raw = '''{"questions":[{"topic":"Mitosis","question":"Why does mitosis occur?","options":["Growth","Digestion","Breathing","Photosynthesis"],"correct_answer":"Growth","explanation":"It supports growth."}]}'''

        questions = parse_questions(raw)

        self.assertEqual(questions[0]["topic"], "Mitosis")
        self.assertEqual(questions[0]["correct_answer"], "Growth")

    def test_parse_questions_rejects_invalid_questions(self) -> None:
        with self.assertRaises(ValueError):
            parse_questions('{"questions":[{"topic":"Bad"}]}')

    def test_large_question_source_is_split_without_losing_text(self) -> None:
        source = "A" * 75_000
        chunks = split_question_source(source, 3)

        self.assertEqual(len(chunks), 4)
        self.assertEqual("".join(chunks), source)
        self.assertLessEqual(max(len(chunk) for chunk in chunks), 20_000)

    def test_chapter_references_and_tiny_sections_do_not_become_boundaries(self) -> None:
        source = (
            "Chapter 6: Functions\n" + "A" * 5_000
            + "\n\nChapter 7 is compared later in this chapter.\n"
            + "B" * 1_000
            + "\n\nChapter 7: Exponentials\n" + "C" * 5_000
            + "\n\nChapter 8: Review\n" + "D" * 200
        )

        sections = _semantic_sections(source)

        self.assertEqual(len(sections), 2)
        self.assertIn("Chapter 7 is compared", sections[0])
        self.assertIn("Chapter 8: Review", sections[1])

    def test_twenty_questions_are_planned_as_small_saved_batches(self) -> None:
        batches = plan_question_batches("A" * 75_000, 20)

        self.assertEqual(len(batches), 4)
        self.assertEqual([question_count for _, question_count in batches], [5, 5, 5, 5])
        self.assertLessEqual(max(len(source) for source, _ in batches), 20_000)


if __name__ == "__main__":
    unittest.main()
