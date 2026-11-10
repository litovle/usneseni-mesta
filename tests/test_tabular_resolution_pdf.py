import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phase1_parse_pdf import main, parse_pdf
from phase2_resolution_analysis import process_usneseni
from phase3_resolve_references import process_resolutions
from tools.tabular_resolution_pdf import is_tabular_resolution_pdf, parse_pages, parse_tables
from tools.sync_litovel_notices import existing_resolution_keys, sync_notices


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "tests/fixtures/tabular_zm_1_2026.pdf"
HEADER = ["Číslo\nusnesení", "Text usnesení", "Datum\njednání", "Zodpovídá", "Termín", "Hlasování", "Ukonč."]


def row(label="UZ-1-1/26", body="Zastupitelstvo města Litovel schvaluje opravu školy.", datum="2. 11. 2026"):
    return [label, "Bod programu: Oprava školy\nText přijatého usnesení:\n" + body,
            datum, "Odpovědná osoba", "16. 11. 2026", "pro: 20 proti: 0 zdržel se: 0", "9. 11. 2026"]


class TabularResolutionPdfTest(unittest.TestCase):
    def test_actual_pdf_detects_and_parses_all_twelve_resolutions(self):
        records, error = parse_pdf(PDF)
        self.assertIsNone(error)
        self.assertEqual([r["id"] for r in records], [f"UZ-{n}-1/26" for n in range(1, 13)])
        self.assertTrue(all("source_id" not in r for r in records))
        self.assertEqual({r["datum"] for r in records}, {"2026-11-02"})
        self.assertEqual({r["organ"] for r in records}, {"Zastupitelstvo města Litovel"})
        self.assertEqual({r["source_format"] for r in records}, {"tabular"})
        self.assertEqual(records[0]["text_raw"], "Zastupitelstvo města Litovel schvaluje aktualizovaný návrh programu jednání.")
        self.assertEqual(records[0]["agenda_title"], "Schválení programu jednání")
        self.assertIn("c) Zastupitelstvo", records[2]["text_raw"])
        self.assertIn("l) Zastupitelstvo", records[-1]["text_raw"])
        for record in records:
            self.assertNotIn("Text přijatého usnesení", record["text_raw"])
            self.assertNotIn("pro:", record["text_raw"])
            self.assertNotIn("Bc. Monika", record["text_raw"])

    def test_detection_requires_table_headers_and_resolution_numbers(self):
        self.assertTrue(is_tabular_resolution_pdf("Text usnesení Datum jednání Hlasování UR-12-2/26"))
        self.assertFalse(is_tabular_resolution_pdf("Číslo: RM/1/1/2026\nRada schvaluje tabulkový přehled, viz UR-1-1/26."))

    def test_council_ids_dates_and_provenance_are_preserved(self):
        records = parse_tables([[HEADER, row("UR-12-2/2026", "Rada města Litovel schvaluje opravu školy.")]], {"source_pdf": "source.pdf"})
        self.assertEqual(records[0]["id"], "UR-12-2/2026")
        self.assertEqual(records[0]["organ"], "Rada města Litovel")
        self.assertEqual(records[0]["source_pdf"], "source.pdf")
        self.assertEqual(parse_tables([[HEADER, row("UZ-001-01/26")]])[0]["id"], "UZ-001-01/26")

    def test_a_decision_can_continue_on_the_next_page(self):
        first = row(body="Zastupitelstvo města Litovel schvaluje")
        continuation = [None, "opravu školy.\nb) Zastupitelstvo města Litovel ukládá zajistit realizaci.", None, None, None, None, None]
        records = parse_tables([[HEADER, first], [HEADER, continuation, row("UZ-2-1/26")]])
        self.assertEqual(len(records), 2)
        self.assertIn("schvaluje\nopravu školy.", records[0]["text_raw"])
        self.assertIn("b) Zastupitelstvo", records[0]["text_raw"])

    def test_invalid_rows_fail_instead_of_publishing_a_partial_document(self):
        cases = [
            [HEADER, row(), row()],
            [HEADER, row(datum="31. 2. 2026")],
            [HEADER, row(datum="2. 11. 2025")],
            [HEADER, ["UZ-1-1/26", "Bod programu bez textu rozhodnutí", "2. 11. 2026", "", "", "", ""]],
            [HEADER, row("XX-1-1/26")],
            [HEADER, [None, "osiřelé pokračování", None, None, None, None, None]],
            [["Neznámá hlavička"], ["UZ-1-1/26"]],
        ]
        for table in cases:
            with self.subTest(table=table), self.assertRaises(ValueError):
                parse_tables([table])

    def test_rows_missed_by_table_extraction_are_reported(self):
        class Page:
            def dedupe_chars(self):
                return self

            def extract_tables(self):
                return [[HEADER, row()]]

            def extract_text(self):
                return "UZ-1-1/26 Bod programu: První\nUZ-2-1/26 Bod programu: Druhý"

        with self.assertRaisesRegex(ValueError, "nesouhlasí"):
            parse_pages([Page()])

    def test_analysis_preserves_organs_actions_and_original_item_text(self):
        raw = parse_tables([[HEADER, row(body="a) Zastupitelstvo města Litovel neschvaluje prodej pozemku.\nb) Zastupitelstvo města Litovel revokuje usnesení UZ-2-1/26.")]])[0]
        parsed = process_usneseni(raw)
        self.assertEqual(parsed["organ"], "Zastupitelstvo města Litovel")
        self.assertEqual(parsed["actions"], ["neschvaluje", "revokuje"])
        self.assertTrue(parsed["items"][0]["text"].startswith("Zastupitelstvo města Litovel"))
        self.assertEqual(parsed["id"], "UZ-1-1/26")
        target = process_usneseni(parse_tables([[HEADER, row("UZ-2-1/26")]])[0])
        records, references, stats = process_resolutions([parsed, target], terms=[])
        self.assertEqual(records[0]["references_out"][0], {"raw": "UZ-2-1/26", "type": "explicit", "resolved": "UZ-2-1/26"})
        self.assertEqual(references[(parsed["id"], "UZ-2-1/26")], "UZ-2-1/26")
        self.assertEqual(records[1]["references_in"][0]["from"], "UZ-1-1/26")

    def test_cli_writes_the_actual_pdf_as_normal_phase1_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, str(ROOT / "phase1_parse_pdf.py"), "--strict", str(PDF), tmp], check=True, capture_output=True, text=True)
            paths = sorted(Path(tmp).glob("*.json"))
            self.assertEqual(len(paths), 12)
            record = json.loads((Path(tmp) / "UZ-1-1-26.json").read_text())
            self.assertEqual(record["id"], "UZ-1-1/26")

    def test_real_pdf_and_existing_records_survive_the_export_pipeline_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run(script, *args):
                subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                               cwd=ROOT, check=True, capture_output=True, text=True)

            run("phase1_parse_pdf.py", "--strict", PDF, root / "phase1")
            legacy_id = "ZM/1/28/2026"
            (root / "phase1/ZM-1-28-2026.json").write_text(json.dumps({
                "id": legacy_id, "datum": "2026-09-14", "organ": "Zastupitelstvo města Litovel",
                "text_raw": "Zastupitelstvo města Litovel schvaluje program jednání.",
            }), encoding="utf-8")
            run("phase2_resolution_analysis.py", "--input", root / "phase1", "--output", root / "phase2")
            run("phase3_resolve_references.py", "--input", root / "phase2", "--output", root / "phase3")
            run("phase4_index_build.py", "--input", root / "phase3/usneseni.json", "--output", root / "export/assets/usneseni")
            run("phase5_static_export.py", "--input", root / "phase3/usneseni.json", "--output", root / "export", "--without-budget")

            expected_ids = {f"UZ-{n}-1/26" for n in range(1, 13)} | {legacy_id}
            records = json.loads((root / "export/assets/usneseni/data/2026.json").read_text())
            index = json.loads((root / "export/assets/usneseni/index/2026.json").read_text())
            self.assertEqual({record["id"] for record in records}, expected_ids)
            self.assertEqual(set(index["ids"]), expected_ids)
            self.assertFalse((root / "export/assets/usneseni/data/26.json").exists())
            sitemap = (root / "export/sitemap-usneseni.xml").read_text()
            for rid in expected_ids:
                with self.subTest(rid=rid):
                    hits = [index["ids"][position] for position in index["tokens"][rid.lower()]]
                    self.assertEqual(hits, [rid])
                    path = f"usneseni/2026/{rid.replace('/', '-')}/"
                    page = (root / "export" / path / "index.html").read_text()
                    self.assertIn(f'cislo: "{rid}"', page)
                    self.assertIn(f"https://litovle.cz/{path}", sitemap)
            self.assertFalse((root / "export/usneseni/2026/ZM-1-1-2026").exists())

    def test_failed_pdf_returns_a_nonzero_exit_code_for_actions(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("sys.argv", ["phase1_parse_pdf.py", "--strict", str(PDF), tmp]), \
                patch("phase1_parse_pdf.parse_pdf", return_value=([], "neznámý formát")), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 1)

    def test_non_strict_import_reports_unsupported_historical_pdfs(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                patch("sys.argv", ["phase1_parse_pdf.py", str(PDF), tmp]), \
                patch("phase1_parse_pdf.parse_pdf", return_value=([], "historický formát")), \
                contextlib.redirect_stdout(output):
            main()
        self.assertIn("historický formát", output.getvalue())

    def test_sync_downloads_detects_parses_and_then_skips_the_new_notice(self):
        board = '<table class="uredni_deska_vypis"><tr><td>UZ-1-1/26</td><td>9.11.2026–4.12.2026</td><td><a href="/detail">Výpis usnesení č.1/2026 ze Zastupitelstva města Litovel, konané dne 2.11 2026</a></td><td>MěÚ Litovel</td><td>Výpis z usnesení</td></tr></table>'
        detail = '<a href="/filemanager/files/file.php?file=5228013" title="*.pdf">Schválená usnesení z jednání č.1/2026</a>'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = dict(notice_url="https://www.litovel.eu/board", resources_dir=root / "resources",
                        ro_dir=root / "ro", workdir=root / "work", dry_run=False)
            with patch("tools.sync_litovel_notices.fetch_text", side_effect=[board, detail]), \
                    patch("tools.sync_litovel_notices.download_pdf", return_value=PDF.read_bytes()):
                downloaded = sync_notices(**args)
            self.assertEqual(len(downloaded), 1)
            self.assertEqual(downloaded[0].key, "ZM/1/2026")
            self.assertEqual(Path(downloaded[0].path).parent, root / "resources/zastupitelstvo")
            self.assertEqual(len(parse_pdf(Path(downloaded[0].path))[0]), 12)
            self.assertIn("ZM/1/2026", existing_resolution_keys(root / "work", root / "resources"))
            with patch("tools.sync_litovel_notices.fetch_text", return_value=board) as fetch:
                self.assertEqual(sync_notices(**args), [])
            self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
