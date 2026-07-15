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

    def test_imported_lesson_persists_after_course_reload(self) -> None:
        course_id = database.create_course("Advanced Functions", "Mathematics", None)
        database.create_study_note(course_id, "Imported transformations", "A saved explanation.")
        reloaded_course = next(course for course in database.list_courses() if course["id"] == course_id)
        notes = database.list_study_notes(reloaded_course["id"])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["title"], "Imported transformations")

    def test_installed_course_keeps_pack_identity_after_reload(self) -> None:
        pack = {"id": "ontario-mhf4u-v1", "title": "Advanced Functions", "subject": "Mathematics", "version": "1.0"}
        course_id = database.install_course_pack(pack, [])
        reloaded = next(course for course in database.list_courses() if course["id"] == course_id)
        self.assertEqual(reloaded["course_pack_id"], "ontario-mhf4u-v1")
        self.assertEqual(reloaded["course_pack_version"], "1.0")

    def test_generated_material_is_saved_once_with_its_source_note(self) -> None:
        course_id = database.create_course("Biology", "Science", None)
        database.create_study_note(course_id, "Cells", "Cells divide.")
        note_id = database.list_study_notes(course_id)[0]["id"]
        material = {
            "flashcards": [{"front": "Mitosis", "back": "Cell division"}],
            "questions": [{"topic": "Cells", "question": "What divides?", "options": ["Cells", "Rocks", "Clouds", "Stars"], "correct_answer": "Cells", "explanation": "The note states cells divide."}],
        }
        database.save_generated_material(course_id, note_id, material)
        self.assertEqual(len(database.list_flashcards(course_id)), 1)
        self.assertEqual(len(database.list_quiz_questions(course_id)), 1)
        with self.assertRaises(ValueError):
            database.save_generated_material(course_id, note_id, material)


if __name__ == "__main__":
    unittest.main()
