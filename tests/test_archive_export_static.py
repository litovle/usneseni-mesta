import tempfile
import unittest
from pathlib import Path

from tools.archive_build_search_index import build_payload
from tools.archive_export_static import build_archive_groups, export_archive_indexes, export_records


def archive_document(record_id="ZM-archive-2022-34-usneseni"):
    return {
        "id": record_id,
        "type": "archive_document",
        "kind": "usneseni",
        "org": "ZM",
        "organ": "Zastupitelstvo města Litovel",
        "title": "Usnesení z 34. zasedání zastupitelstva města",
        "date": "2022-09-15",
        "year": 2022,
        "period": "2018-2022",
        "meeting_no": 34,
        "source_url": "https://www.litovel.eu/archive",
        "original_file_url": "https://www.litovel.eu/filemanager/files/2344691.pdf",
        "file_type": "pdf",
        "text_quality": {"quality_flag": "text_ok"},
        "search_text": "Schvaluje opravu chodníku.",
        "display_text": "Schvaluje opravu chodníku.",
    }


def archive_resolution(parent_id, ordinal, resolution_no):
    return {
        "id": f"{parent_id}-resolution-{ordinal:03d}-{resolution_no}",
        "type": "archive_resolution",
        "kind": "usneseni",
        "parent_document_id": parent_id,
        "org": "ZM",
        "organ": "Zastupitelstvo města Litovel",
        "title": f"Archivní usnesení {resolution_no}",
        "date": "2022-09-15",
        "year": 2022,
        "period": "2018-2022",
        "meeting_no": 34,
        "resolution_no": resolution_no,
        "search_text": f"{resolution_no}. Schvaluje opravu chodníku v Litovli.",
        "display_text": f"{resolution_no}. Schvaluje opravu chodníku v Litovli.",
    }


class ArchiveExportStaticTest(unittest.TestCase):
    def test_archive_index_groups_split_document_and_writes_parent_page(self):
        parent = archive_document()
        children = [
            archive_resolution(parent["id"], 1, "1"),
            archive_resolution(parent["id"], 2, "2"),
        ]
        by_year, report = build_payload([parent], children)
        records = [record for items in by_year.values() for record in items]
        groups = build_archive_groups(records, [parent])

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            detail_count = export_records(records, output)
            detail_html = (output / "usneseni" / "archiv" / children[0]["id"] / "index.html").read_text(encoding="utf-8")
            index_count = export_archive_indexes(groups, report, output)
            index_html = (output / "usneseni" / "archiv" / "index.html").read_text(encoding="utf-8")
            parent_html = (output / "usneseni" / "archiv" / parent["id"] / "index.html").read_text(encoding="utf-8")

        self.assertEqual(detail_count, 2)
        self.assertEqual(index_count, 2)
        self.assertIn('<script src="/usneseni/back-link.js" defer></script>', detail_html)
        self.assertNotIn("<script>", detail_html)
        self.assertIn("Archiv usnesení", index_html)
        self.assertIn("2022", index_html)
        self.assertIn("Zastupitelstvo", index_html)
        self.assertIn("2 usnesení", index_html)
        self.assertIn(f'/usneseni/archiv/{parent["id"]}/', index_html)
        self.assertIn("/usneseni/archiv/ZM-archive-2022-34-usneseni-resolution-001-1/", parent_html)
        self.assertIn("Schvaluje opravu chodníku", parent_html)

    def test_archive_index_links_unsplit_fallback_document_directly(self):
        parent = archive_document()
        by_year, report = build_payload([parent], [])
        records = [record for items in by_year.values() for record in items]
        groups = build_archive_groups(records, [parent])

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            detail_count = export_records(records, output)
            index_count = export_archive_indexes(groups, report, output)
            index_html = (output / "usneseni" / "archiv" / "index.html").read_text(encoding="utf-8")

        self.assertEqual(detail_count, 1)
        self.assertEqual(index_count, 1)
        self.assertIn(f'/usneseni/archiv/{parent["id"]}/', index_html)
        self.assertNotIn('class="usn-archive-meeting-count">dokument</span>', index_html)
        self.assertIn("nerozdělených dokumentů", index_html)

    def test_archive_index_excludes_promoted_documents(self):
        parent = archive_document()
        child = archive_resolution(parent["id"], 1, "1")
        by_year, report = build_payload([parent], [child], {parent["id"]})
        records = [record for items in by_year.values() for record in items]
        groups = build_archive_groups(records, [parent])

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            export_archive_indexes(groups, report, output)
            index_html = (output / "usneseni" / "archiv" / "index.html").read_text(encoding="utf-8")

        self.assertNotIn(parent["title"], index_html)
        self.assertNotIn(child["id"], index_html)


if __name__ == "__main__":
    unittest.main()
