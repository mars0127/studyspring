"""Checks for the starter-course catalogue."""

import unittest

from course_starters import COURSE_STARTERS


class CourseStarterTests(unittest.TestCase):
    def test_common_senior_math_and_english_courses_are_available(self) -> None:
        expected_codes = {"MCR3U", "MHF4U", "MCV4U", "MDM4U", "ENG2D", "ENG3U", "ENG4U"}
        available_codes = {name.split(" ")[0] for name in COURSE_STARTERS}

        self.assertTrue(expected_codes.issubset(available_codes))

    def test_kinesiology_is_not_a_starter_course(self) -> None:
        self.assertFalse(any("Kinesiology" in name for name in COURSE_STARTERS))


if __name__ == "__main__":
    unittest.main()
