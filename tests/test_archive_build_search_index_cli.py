import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from tools.archive_build_search_index import main


class ArchiveBuildSearchIndexCliTest(unittest.TestCase):
    def test_default_command_uses_generated_split_resolutions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_root = root / "work" / "archive_zm"
            archive_root.mkdir(parents=True)

            parent = {
                "id": "ZM-archive-2022-34-usneseni",
                "type": "archive_document",
                "kind": "usneseni",
                "org": "ZM",
                "organ": "Zastupitelstvo města Litovel",
                "title": "Usnesení z 34. zasedání zastupitelstva města",
                "date": "2022-09-15",
                "year": 2022,
                "meeting_no": 34,
                "text_quality": {"quality_flag": "text_ok"},
                "search_text": "Parent fallback text.",
                "display_text": "Parent fallback text.",
            }
            child = {
                "id": "ZM-archive-2022-34-usneseni-resolution-001-1",
                "type": "archive_resolution",
                "kind": "usneseni",
                "parent_document_id": parent["id"],
                "org": "ZM",
                "organ": "Zastupitelstvo města Litovel",
                "title": "Archivní usnesení 1",
                "date": "2022-09-15",
                "year": 2022,
                "meeting_no": 34,
                "resolution_no": "1",
                "search_text": "Schvaluje opravu chodníku.",
                "display_text": "Schvaluje opravu chodníku.",
            }

            (archive_root / "archive_documents.json").write_text(
                json.dumps([parent], ensure_ascii=False),
                encoding="utf-8",
            )
            (archive_root / "archive_resolutions.json").write_text(
                json.dumps([child], ensure_ascii=False),
                encoding="utf-8",
            )

            old_cwd = Path.cwd()
            old_argv = sys.argv[:]
            try:
                os.chdir(root)
                sys.argv = ["archive_build_search_index.py"]
                self.assertEqual(main(), 0)
            finally:
                os.chdir(old_cwd)
                sys.argv = old_argv

            report = json.loads((archive_root / "search_index_report.json").read_text(encoding="utf-8"))
            data = json.loads((archive_root / "search_index" / "data" / "2022.json").read_text(encoding="utf-8"))
            index = json.loads((archive_root / "search_index" / "index" / "2022.json").read_text(encoding="utf-8"))

        self.assertEqual(report["indexed_archive_resolutions"], 1)
        self.assertEqual(report["fallback_archive_documents"], 0)
        self.assertEqual(report["skipped_split_parents"], 1)
        self.assertEqual([record["id"] for record in data], [child["id"]])
        self.assertEqual([index["ids"][position] for position in index["tokens"]["chodnik"]], [child["id"]])


if __name__ == "__main__":
    unittest.main()
