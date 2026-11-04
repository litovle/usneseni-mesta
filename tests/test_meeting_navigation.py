import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from static_export.usneseni import build_meeting_navigation


def resolution(rid, date="2026-10-22"):
    return {"id": rid, "datum": date, "organ": "Rada města Litovel", "subject": "program schůze", "actions": ["schvaluje"], "items": []}


class MeetingNavigationTest(unittest.TestCase):
    def test_numeric_order_gaps_and_meeting_boundaries(self):
        ids = ["RM/12/82/2026", "RM/2/82/2026", "RM/9/82/2026"]
        nav = build_meeting_navigation([resolution(rid) for rid in ids])
        self.assertEqual(nav[ids[1]], {"next": {"id": ids[2], "url": "/usneseni/2026/RM-9-82-2026/"}})
        self.assertEqual(nav[ids[2]]["previous"]["id"], ids[1])
        self.assertEqual(nav[ids[2]]["next"]["id"], ids[0])
        self.assertEqual(nav[ids[0]], {"previous": {"id": ids[2], "url": "/usneseni/2026/RM-9-82-2026/"}})

    def test_navigation_never_crosses_organ_meeting_or_year(self):
        rows = [resolution("RM/2/82/2026"), resolution("RM/9/82/2026"),
                resolution("RM/1/83/2026"), resolution("ZM/1/82/2026"),
                resolution("RM/1/82/2025", "2025-10-22")]
        nav = build_meeting_navigation(rows)
        for row in rows[2:]:
            self.assertEqual(nav[row["id"]], {})
        self.assertNotIn("next", nav["RM/9/82/2026"])

    def test_records_that_cannot_be_exported_are_not_link_targets(self):
        rows = [resolution("RM/2/82/2026"), {"id": "RM/3/82/2026"},
                resolution("RO/1/2026"), resolution("RM/4/82/2025", "2026-10-22")]
        self.assertEqual(build_meeting_navigation(rows), {"RM/2/82/2026": {}})

    def test_cli_exports_navigation_metadata_for_every_position(self):
        rows = [resolution("RM/12/82/2026"), resolution("RM/2/82/2026"),
                resolution("RM/9/82/2026"), resolution("RM/1/83/2026")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "resolutions.json"
            source.write_text(json.dumps(rows), encoding="utf-8")
            subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "phase5_static_export.py"),
                            "--input", str(source), "--output", str(root / "output"), "--without-budget"],
                           check=True, capture_output=True, text=True)
            pages = {row["id"]: (root / "output/usneseni/2026" / row["id"].replace("/", "-") / "index.html").read_text() for row in rows}
        for rid in ["RM/2/82/2026", "RM/9/82/2026", "RM/12/82/2026"]:
            line = next(line for line in pages[rid].splitlines() if line.startswith("meeting_navigation: "))
            nav = json.loads(line.removeprefix("meeting_navigation: "))
            self.assertEqual(nav, build_meeting_navigation(rows)[rid])
        self.assertNotIn("meeting_navigation:", pages["RM/1/83/2026"])


if __name__ == "__main__":
    unittest.main()
