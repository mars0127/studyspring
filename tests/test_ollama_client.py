"""Tests for safely accepting Gemini quiz output."""

import json
import unittest
from unittest.mock import patch

from gemini_client import (
    MAX_SOURCE_CHARACTERS_PER_REQUEST,
    _semantic_sections,
    generate_question_batch,
    parse_questions,
    plan_question_batches,
    split_question_source,
)


class GeminiClientTests(unittest.TestCase):
    def test_question_batch_uses_small_rest_request(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": '{"questions":[{"topic":"Cells","question":"What is mitosis for?","options":["Growth","Digestion","Breathing","Movement"],"correct_answer":"Growth","explanation":"Growth and repair."}]}'
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        with patch("gemini_client.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            questions = generate_question_batch(
                "test-key", "Mitosis supports growth.", 1, "Cell division"
            )

        self.assertEqual(questions[0]["correct_answer"], "Growth")
        self.assertEqual(questions[0]["topic"], "Cell division")
        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["generationConfig"]["response_mime_type"], "application/json")
        self.assertIn(
            'Use "Cell division" as the topic value',
            payload["contents"][0]["parts"][0]["text"],
        )
        self.assertNotIn("test-key", request.full_url)
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

        self.assertEqual(len(chunks), 7)
        self.assertEqual("".join(chunks), source)
        self.assertLessEqual(max(len(chunk) for chunk in chunks), MAX_SOURCE_CHARACTERS_PER_REQUEST)

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

        self.assertEqual(len(batches), 7)
        self.assertEqual([question_count for _, question_count in batches], [3, 3, 3, 3, 3, 3, 2])
        self.assertLessEqual(
            max(len(source) for source, _ in batches), MAX_SOURCE_CHARACTERS_PER_REQUEST
        )

    def test_render_sized_source_keeps_twenty_questions_to_four_requests(self) -> None:
        batches = plan_question_batches("A" * 36_000, 20)

        self.assertEqual(len(batches), 4)
        self.assertEqual([question_count for _, question_count in batches], [5, 5, 5, 5])
        self.assertLessEqual(
            max(len(source) for source, _ in batches), MAX_SOURCE_CHARACTERS_PER_REQUEST
        )


if __name__ == "__main__":
    unittest.main()
