"""Tests for safely accepting Gemini quiz output."""

import unittest

from gemini_client import parse_questions


class GeminiClientTests(unittest.TestCase):
    def test_parse_questions_keeps_valid_question(self) -> None:
        raw = '''{"questions":[{"topic":"Mitosis","question":"Why does mitosis occur?","options":["Growth","Digestion","Breathing","Photosynthesis"],"correct_answer":"Growth","explanation":"It supports growth."}]}'''

        questions = parse_questions(raw)

        self.assertEqual(questions[0]["topic"], "Mitosis")
        self.assertEqual(questions[0]["correct_answer"], "Growth")

    def test_parse_questions_rejects_invalid_questions(self) -> None:
        with self.assertRaises(ValueError):
            parse_questions('{"questions":[{"topic":"Bad"}]}')


if __name__ == "__main__":
    unittest.main()
