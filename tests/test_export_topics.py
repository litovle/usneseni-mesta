import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from static_export.topics import TOPIC_LABELS, topic_catalog
from static_export.usneseni import write_resolution


class ExportTopicsTest(unittest.TestCase):
    def test_catalog_labels_and_unknown_categories(self):
        catalog = topic_catalog([
            {"classification": {"category": "transport"}},
            {"classification": {"category": "new_domain"}},
            {"classification": {"category": None}},
            {},
        ])
        self.assertEqual(catalog["transport"], "Doprava")
        self.assertEqual(catalog["new_domain"], "new_domain")
        self.assertEqual(len(TOPIC_LABELS), 14)
        self.assertNotIn(None, catalog)

    def test_yearly_data_and_topic_frontmatter(self):
        rows = [{"id": "RM/1/1/2026", "datum": "2026-10-29", "organ": "RM",
                 "subject": "Oprava chodníku", "items": [],
                 "classification": {"category": "transport", "model_sha256": "a" * 64}},
                {"id": "RM/2/1/2026", "datum": "2026-10-29", "organ": "RM", "items": []}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.json"
            source.write_text(json.dumps(rows))
            subprocess.run([sys.executable, "phase4_index_build.py", "--input", str(source),
                            "--output", str(root / "assets")], check=True, capture_output=True)
            self.assertEqual(json.loads((root / "assets/data/2026.json").read_text()), rows)
            self.assertEqual(json.loads((root / "assets/topics.json").read_text())["transport"], "Doprava")
            for row in rows:
                write_resolution(row, root, {}, {})
            classified = (root / "usneseni/2026/RM-1-1-2026/index.html").read_text()
            self.assertIn('classification_category: "transport"', classified)
            self.assertIn('classification_label: "Doprava"', classified)
            unclassified = (root / "usneseni/2026/RM-2-1-2026/index.html").read_text()
            self.assertNotIn("classification_category:", unclassified)

    def test_unknown_category_frontmatter_is_escaped(self):
        row = {"id": "RM/1/1/2026", "datum": "2026-10-29", "organ": "RM",
               "classification": {"category": 'new "topic"'}}
        with tempfile.TemporaryDirectory() as directory:
            write_resolution(row, Path(directory), {}, {})
            text = (Path(directory) / "usneseni/2026/RM-1-1-2026/index.html").read_text()
            self.assertIn('classification_label: ' + json.dumps('new "topic"'), text)
