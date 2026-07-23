"""Basic automated checks for StudySpring's data layer."""

import tempfile
import unittest
from pathlib import Path

import database


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temporary_directory.name) / "test.db"
        database.initialize_database()

    def tearDown(self) -> None:
        database.DATABASE_PATH = self.original_path
        self.temporary_directory.cleanup()

    def test_course_notes_questions_and_attempts_are_saved(self) -> None:
        database.create_course("Biology", "Science", None)
        course = database.list_courses()[0]
        database.create_study_note(course["id"], "Cells", "Mitosis makes identical cells.")
        database.create_flashcard(course["id"], "Mitosis purpose", "Growth and repair")
        database.create_quiz_question(
            course["id"],
            "Mitosis",
            "What is mitosis for?",
            ["Growth", "Digestion", "Breathing", "Movement"],
            "Growth",
            "Mitosis supports growth and repair.",
        )

        question = database.list_quiz_questions(course["id"])[0]
        database.record_quiz_attempt(question["id"], "Growth", True)

        attempts, accuracy = database.course_quiz_stats(course["id"])
        self.assertEqual(attempts, 1)
        self.assertEqual(accuracy, 100.0)
        self.assertEqual(database.list_flashcards(course["id"])[0]["front"], "Mitosis purpose")
        self.assertEqual(database.course_topic_stats(course["id"])[0]["topic"], "Mitosis")

    def test_course_update_and_delete_remove_related_data(self) -> None:
        database.create_course("Chemistry", "Science", "2026-12-01")
        course = database.list_courses()[0]
        database.create_study_note(course["id"], "Atoms", "Atoms contain protons.")
        database.update_course(course["id"], "Chemistry 12", "Science", None)

        self.assertEqual(database.list_courses()[0]["name"], "Chemistry 12")
        database.delete_course(course["id"])

        self.assertEqual(database.list_courses(), [])
        self.assertEqual(database.list_study_notes(course["id"]), [])

    def test_import_note_can_be_saved_in_batches(self) -> None:
        database.create_course("Physics", "Science", None)
        course = database.list_courses()[0]
        note_id = database.create_study_note(course["id"], "Importing", "Working...")
        database.replace_study_note_content(note_id, "Page 1")
        database.append_study_note_content(note_id, "Page 2")
        database.rename_study_note(note_id, "Physics notes")

        note = database.list_study_notes(course["id"])[0]
        self.assertEqual(note["title"], "Physics notes")
        self.assertEqual(note["content"], "Page 1\n\nPage 2")

    def test_note_summaries_do_not_load_large_note_text(self) -> None:
        database.create_course("Memory test", "Science", None)
        course = database.list_courses()[0]
        note_id = database.create_study_note(course["id"], "Large note", "A" * 200_000)

        summary = database.list_study_notes(course["id"], include_content=False)[0]
        full_note = database.get_study_note(note_id)

        self.assertNotIn("content", summary.keys())
        self.assertEqual(summary["content_length"], 200_000)
        self.assertEqual(full_note["content"], "A" * 200_000)

    def test_large_note_preview_and_excerpt_stay_bounded(self) -> None:
        database.create_course("Memory test", "Science", None)
        course = database.list_courses()[0]
        note_id = database.create_study_note(course["id"], "Large note", "A" * 200_000)

        self.assertEqual(len(database.get_study_note_preview(note_id, 500)), 500)
        excerpt = database.get_study_note_excerpt(note_id, 3_000, piece_count=3)
        self.assertLessEqual(len(excerpt), 3_000)
        self.assertIn("A", excerpt)

        database.update_study_note_metadata(note_id, "Renamed", "Unit 1", "Chapter 1", "Lesson 1")
        summary = database.list_study_notes(course["id"], include_content=False)[0]
        self.assertEqual(summary["title"], "Renamed")
        self.assertEqual(summary["content_length"], 200_000)

    def test_ai_question_batch_is_saved_atomically(self) -> None:
        database.create_course("Math", "Mathematics", None)
        course = database.list_courses()[0]
        database.create_quiz_questions(
            course["id"],
            [
                {
                    "topic": "Functions",
                    "question": "What is the domain?",
                    "options": ["Inputs", "Outputs", "Slope", "Intercept"],
                    "correct_answer": "Inputs",
                    "explanation": "The domain is the set of inputs.",
                },
                {
                    "topic": "Functions",
                    "question": "What is the range?",
                    "options": ["Outputs", "Inputs", "Slope", "Intercept"],
                    "correct_answer": "Outputs",
                    "explanation": "The range is the set of outputs.",
                },
            ],
        )
        self.assertEqual(len(database.list_quiz_questions(course["id"])), 2)


if __name__ == "__main__":
    unittest.main()
