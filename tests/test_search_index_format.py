import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from phase4_index_build import build_index as resolution_index
from phase4_ro_index_build import build_index as budget_index
from tools.search_index_format import compact_index, write_compact_index

ROOT = Path(__file__).resolve().parents[1]


def expand(payload):
    return {
        term: [payload["ids"][position] for position in hits]
        for term, hits in payload["tokens"].items()
    }


class SearchIndexFormatTest(unittest.TestCase):
    def test_round_trip_preserves_postings_and_reserved_terms(self):
        index = {
            "skol": ["ZM/archive/2", "RM/archive/1"],
            "skola": ["RM/archive/1"],
            "ids": ["ZM/archive/2"],
            "tokens": [],
        }
        packed = compact_index(index)
        self.assertEqual(expand(packed), index)
        self.assertEqual(packed["ids"], ["RM/archive/1", "ZM/archive/2"])
        self.assertEqual(packed["tokens"]["skol"], [1, 0])

    def test_empty_index_has_an_empty_id_table(self):
        self.assertEqual(compact_index({}), {"ids": [], "tokens": {}})

    def test_writer_is_compact_deterministic_and_preserves_unicode(self):
        document_id = "RM-archive-2010-69-usneseni-resolution-001-1313-69-škola"
        index = {f"term{number}": [document_id] for number in range(100)}
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "index" / "2026.json"
            second = Path(tmp) / "other.json"
            write_compact_index(first, index)
            write_compact_index(second, dict(reversed(list(index.items()))))
            text = first.read_text(encoding="utf-8")
            self.assertEqual(expand(json.loads(text)), index)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertIn("škola", text)
            self.assertLess(first.stat().st_size, len(json.dumps(index).encode()) / 2)

    def test_resolution_and_budget_commands_write_equivalent_compact_indexes(self):
        cases = [
            ("phase4_index_build.py", resolution_index, [
                {"id": "RM/1/1/2026", "subject": "Oprava školy", "items": []},
                {"id": "RM/2/1/2026", "subject": "Pronájem pozemku", "items": []},
                {"id": "UZ-001-01/26", "subject": "Oprava školy", "items": []},
            ]),
            ("phase4_ro_index_build.py", budget_index, [
                {"id": "RO/1/2026", "notes": [{"title": "Oprava školy"}]},
                {"id": "RO/2/2026", "notes": [{"title": "Pronájem pozemku"}]},
            ]),
        ]
        for script, build_index, records in cases:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if script == "phase4_index_build.py":
                    source = root / "records.json"
                    source.write_text(json.dumps(records), encoding="utf-8")
                else:
                    source = root / "records"
                    source.mkdir()
                    for position, record in enumerate(records):
                        (source / f"{position}.json").write_text(json.dumps(record), encoding="utf-8")
                output = root / "output"
                subprocess.run(
                    [sys.executable, str(ROOT / script), "--input", str(source), "--output", str(output)],
                    cwd=root, check=True, capture_output=True, text=True,
                )
                payload = json.loads((output / "index" / "2026.json").read_text(encoding="utf-8"))
                self.assertEqual(expand(payload), build_index(records))
                expected = [0, 2] if script == "phase4_index_build.py" else [0]
                self.assertEqual(payload["tokens"]["opra"], expected)
                if script == "phase4_index_build.py":
                    self.assertEqual(payload["tokens"]["uz-001-01/26"], [2])
                    self.assertNotIn("ZM/1/1/2026", payload["ids"])
                self.assertEqual(json.loads((output / "data" / "2026.json").read_text()), records)

    def test_archive_command_runs_directly_from_another_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [sys.executable, str(ROOT / "tools/archive_build_search_index.py"), "--help"],
                cwd=tmp, check=True, capture_output=True, text=True,
            )


if __name__ == "__main__":
    unittest.main()
