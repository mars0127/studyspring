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

    def test_pdf_import_pages_are_checkpointed(self) -> None:
        course_id = database.create_course("Biology", "Science", None)
        job_id = database.create_or_resume_pdf_import_job(course_id, "hash", "book.pdf", 1, 2)
        self.assertEqual(job_id, database.create_or_resume_pdf_import_job(course_id, "hash", "book.pdf", 1, 2))
        database.save_pdf_import_page(job_id, 1, "completed", "embedded_text", "Cell notes")
        database.save_pdf_import_page(job_id, 2, "failed", error_message="Unreadable")
        database.complete_pdf_import_job(job_id)
        pages = database.list_pdf_import_pages(job_id)
        self.assertEqual(pages[0]["extracted_text"], "Cell notes")
        self.assertEqual(pages[1]["status"], "failed")
        self.assertEqual(database.list_pdf_import_jobs(course_id)[0]["status"], "partially_completed")

    def test_pdf_import_with_no_completed_pages_is_failed(self) -> None:
        course_id = database.create_course("Biology", "Science", None)
        job_id = database.create_or_resume_pdf_import_job(course_id, "hash-three", "book.pdf", 1, 1)
        database.save_pdf_import_page(job_id, 1, "failed", error_message="Quota")
        database.complete_pdf_import_job(job_id)
        self.assertEqual(database.list_pdf_import_jobs(course_id)[0]["status"], "failed")

    def test_pdf_import_can_be_cancelled_without_losing_completed_pages(self) -> None:
        course_id = database.create_course("Physics", "Science", None)
        job_id = database.create_or_resume_pdf_import_job(course_id, "hash-two", "book.pdf", 1, 2)
        database.save_pdf_import_page(job_id, 1, "completed", "embedded_text", "Saved page")
        database.cancel_pdf_import_job(job_id)
        pages = database.list_pdf_import_pages(job_id)
        self.assertEqual(pages[0]["status"], "completed")
        self.assertEqual(pages[1]["status"], "skipped")
        self.assertEqual(database.list_pdf_import_jobs(course_id)[0]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
