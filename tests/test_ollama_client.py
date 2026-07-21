"""Tests for safely accepting Gemini quiz output."""

import unittest

from gemini_client import parse_questions, split_question_source


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

        self.assertEqual(len(chunks), 3)
        self.assertEqual("".join(chunks), source)
        self.assertLessEqual(max(len(chunk) for chunk in chunks), 25_000)


if __name__ == "__main__":
    unittest.main()
