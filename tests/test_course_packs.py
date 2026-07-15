"""Checks for bundled, installable course content."""

import tempfile
import unittest
from pathlib import Path

import database
from services.course_pack_service import list_course_packs, lesson_text


class CoursePackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.temporary_directory.name) / "test.db"
        database.initialize_database()

    def tearDown(self) -> None:
        database.DATABASE_PATH = self.original_path
        self.temporary_directory.cleanup()

    def test_mhf4u_pack_is_valid_and_installs_once(self) -> None:
        pack = next(pack for pack in list_course_packs() if pack["course_code"] == "MHF4U")
        lessons = [(unit, lesson_text(pack, unit)) for unit in pack["units"]]
        course_id = database.install_course_pack(pack, lessons)
        self.assertEqual(course_id, database.install_course_pack(pack, lessons))
        self.assertEqual(len(database.list_courses()), 1)
        self.assertIn("Function foundations", database.list_study_notes(course_id)[0]["title"])
        self.assertEqual(len(database.list_flashcards(course_id)), 2)
        self.assertEqual(len(database.list_quiz_questions(course_id)), 2)


if __name__ == "__main__":
    unittest.main()
