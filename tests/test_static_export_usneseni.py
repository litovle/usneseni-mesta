import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from static_export.usneseni import render_resolution_preview, truncate_preview, write_meeting_index, write_resolution


class StaticExportUsneseniTest(unittest.TestCase):
    def test_preview_preserves_subject_and_single_labelled_item(self):
        text = render_resolution_preview({
            "actions": ["schvaluje"], "subject": "Změny programu", "items": [
                {"label": "a", "text": "schvaluje doplnění programu"},
            ],
        })
        self.assertIn('class="usn-summary">schvaluje</div>', text)
        self.assertIn('class="usn-snippet">Změny programu</div>', text)
        self.assertIn('class="usn-action-label">a)</strong> schvaluje doplnění programu', text)

    def test_preview_preserves_three_item_order_and_labels(self):
        text = render_resolution_preview({
            "actions": ["bere na vědomí"], "items": [
                {"label": "a", "text": "výroční zpráva školy Jungmannova"},
                {"label": "b", "text": "výroční zpráva školy Vítězná"},
                {"label": "c", "text": "výroční zpráva školy Nasobůrky"},
            ],
        })
        self.assertIn('class="usn-summary">3 rozhodnutí</div>', text)
        self.assertEqual(text.count('<li>'), 3)
        self.assertLess(text.index('Jungmannova'), text.index('Vítězná'))
        self.assertLess(text.index('Vítězná'), text.index('Nasobůrky'))
        self.assertIn('class="usn-action-label">c)</strong>', text)
        self.assertNotIn('class="usn-actions-more"', text)

    def test_preview_limits_items_and_reports_remaining_count(self):
        text = render_resolution_preview({"items": [
            {"label": str(i), "text": f"Rozhodnutí číslo {i}"} for i in range(1, 6)
        ]})
        self.assertEqual(text.count('<li>'), 3)
        self.assertIn('5 rozhodnutí', text)
        self.assertIn('Další 2 rozhodnutí', text)
        self.assertNotIn('Rozhodnutí číslo 4', text)
        self.assertNotIn('Rozhodnutí číslo 5', text)

    def test_preview_escapes_html_and_truncates_long_text(self):
        raw = '<img src=x onerror=alert(1)> & "citace"'
        text = render_resolution_preview({"items": [{"label": '<label>', "text": raw}]})
        self.assertNotIn('<img', text)
        self.assertIn('&lt;img', text)
        self.assertIn('&amp;', text)
        self.assertNotIn('&amp;lt;', text)
        self.assertIn('&lt;label&gt;)', text)
        short = truncate_preview('  Krátký  text\nbez ořezu. ')
        self.assertEqual(short, 'Krátký text bez ořezu.')
        long = truncate_preview('Dlouhý text rozhodnutí ' * 30)
        self.assertLessEqual(len(long), 181)
        self.assertTrue(long.endswith('…'))
        self.assertIn(long, render_resolution_preview({"subject": 'Dlouhý text rozhodnutí ' * 30}))

    def test_export_cli_passes_items_to_meeting_page(self):
        resolution = {
            "id": "RM/2589/82/2026", "datum": "2026-10-22", "organ": "Rada města Litovel",
            "subject": None, "actions": ["bere na vědomí"], "items": [
                {"label": "a", "text": "bere na vědomí výroční zprávu školy Jungmannova"},
                {"label": "b", "text": "bere na vědomí výroční zprávu školy Vítězná"},
                {"label": "c", "text": "bere na vědomí výroční zprávu školy Nasobůrky"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'resolutions.json'
            source.write_text(json.dumps([resolution], ensure_ascii=False), encoding='utf-8')
            subprocess.run([
                sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'phase5_static_export.py'),
                '--input', str(source), '--output', str(root / 'output'), '--without-budget',
            ], check=True, capture_output=True, text=True)
            text = (root / 'output/usneseni/2026/RM-82/index.html').read_text(encoding='utf-8')
        self.assertIn('3 rozhodnutí', text)
        self.assertIn('Jungmannova', text)
        self.assertIn('Vítězná', text)
        self.assertIn('Nasobůrky', text)
        self.assertIn('class="usn-action-label">a)</strong>', text)

    def test_write_resolution_includes_term_frontmatter(self):
        resolution = {
            "id": "RM/1/1/2026",
            "datum": "2026-10-29",
            "organ": "Rada města Litovel",
            "actions": ["schvaluje"],
            "subject": "program schůze",
            "items": [],
            "references_out": [],
            "term_id": "2026-2030",
            "term_label": "Volební období 2026-2030",
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_resolution(resolution, output, {}, {})
            page = output / "usneseni" / "2026" / "RM-1-1-2026" / "index.html"
            text = page.read_text(encoding="utf-8")

        self.assertIn('term_id: "2026-2030"', text)
        self.assertIn('term_label: "Volební období 2026-2030"', text)

    def test_write_meeting_index_includes_term_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_meeting_index(
                "2026",
                "RM",
                "1",
                [("RM/1/1/2026", "/usneseni/2026/RM-1-1-2026/", "program schůze", ["schvaluje"])],
                {
                    "organ": "Rada města Litovel",
                    "datum": "2026-10-29",
                    "term_id": "2026-2030",
                    "term_label": "Volební období 2026-2030",
                },
                output,
            )
            page = output / "usneseni" / "2026" / "RM-1" / "index.html"
            text = page.read_text(encoding="utf-8")

        self.assertIn('term_id: "2026-2030"', text)
        self.assertIn("2026-10-29 • Volební období 2026-2030 • 1 usnesení", text)


if __name__ == "__main__":
    unittest.main()
