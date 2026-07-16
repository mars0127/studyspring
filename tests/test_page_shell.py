import unittest

from pages.views import PAGES


class PageShellTests(unittest.TestCase):
    def test_every_primary_destination_has_a_renderer(self):
        self.assertEqual(set(PAGES), {"Home", "My Courses", "Course Library", "Imports", "Learn", "Progress", "Settings"})
        self.assertTrue(all(callable(renderer) for renderer in PAGES.values()))
