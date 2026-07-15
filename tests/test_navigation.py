import unittest

from components.ui import resolve_page


class NavigationTests(unittest.TestCase):
    def test_navigation_normalizes_missing_or_stale_page(self):
        pages = ["Home", "Imports", "Learn"]
        self.assertEqual(resolve_page(None, pages), "Home")
        self.assertEqual(resolve_page("Unknown", pages), "Home")
        self.assertEqual(resolve_page("Learn", pages), "Learn")

    def test_navigation_keeps_a_valid_course_destination(self):
        self.assertEqual(resolve_page("My Courses", ["Home", "My Courses", "Learn"]), "My Courses")
