import unittest

from services.content_blocks import ContentBlockError, blocks_to_markdown, validate_blocks


class ContentBlockTests(unittest.TestCase):
    def test_valid_blocks_are_normalized_and_renderable(self):
        blocks = validate_blocks([
            {"type": "heading", "content": "A lesson"},
            {"type": "flashcard_set", "cards": [{"front": "Domain", "back": "Allowed inputs"}]},
            {"type": "multiple_choice_set", "questions": [{"question": "Shift?", "options": ["Right", "Left", "Up", "Down"], "correct_answer": "Right"}]},
        ])
        self.assertIn("A lesson", blocks_to_markdown(blocks))
        self.assertEqual(blocks[1]["cards"][0]["front"], "Domain")

    def test_invalid_question_is_rejected(self):
        with self.assertRaises(ContentBlockError):
            validate_blocks([{"type": "multiple_choice_set", "questions": [{"question": "Bad", "options": ["a"], "correct_answer": "a"}]}])
