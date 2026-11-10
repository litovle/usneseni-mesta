import unittest

from tools.resolution_ids import parse_resolution_id
from static_export.paths import resolution_url


class ResolutionIdTest(unittest.TestCase):
    def test_metadata_supports_both_official_schemes(self):
        for value, expected in {
            "RM/12/2/2026": ("RM", 12, 2, 2026),
            "ZM/12/2/2026": ("ZM", 12, 2, 2026),
            "UR-12-2/26": ("RM", 12, 2, 2026),
            "UZ-12-2/2026": ("ZM", 12, 2, 2026),
        }.items():
            with self.subTest(value=value):
                parts = parse_resolution_id(value)
                self.assertEqual((parts.organ, parts.number, parts.meeting, parts.year), expected)

    def test_links_retain_the_source_prefix_number_and_year_spelling(self):
        self.assertEqual(resolution_url("UZ-001-01/26"), "/usneseni/2026/UZ-001-01-26/")
        self.assertEqual(resolution_url("UR-12-2/2026"), "/usneseni/2026/UR-12-2-2026/")
        self.assertEqual(resolution_url("RM/12/2/2026"), "/usneseni/2026/RM-12-2-2026/")

    def test_unknown_identifiers_are_not_reinterpreted(self):
        for value in (None, "", "UZ/12/2/2026", "UZ-1-1/260", "ZM/12/2/26", "other", "UZ-1-1/26/extra"):
            with self.subTest(value=value):
                self.assertIsNone(parse_resolution_id(value))


if __name__ == "__main__":
    unittest.main()
