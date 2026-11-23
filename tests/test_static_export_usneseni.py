import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from static_export.usneseni import render_resolution_content, render_resolution_preview, resolution_seo, truncate_preview, write_meeting_index, write_resolution


class StaticExportUsneseniTest(unittest.TestCase):
    def test_recommendation_before_a_list_keeps_its_governing_action(self):
        from phase2_resolution_analysis import process_usneseni

        record = process_usneseni({
            "id": "UR-3-1/26", "datum": "2026-11-12", "organ": "Rada města Litovel",
            "text_raw": "Rada města Litovel doporučuje Zastupitelstvu města Litovel:\na) schválit záměr prodeje pozemku.\nb) jmenovat komisi.",
        })
        self.assertIn("doporučuje Zastupitelstvu města Litovel", render_resolution_content(record))
        self.assertIn("doporučuje", render_resolution_preview(record))
        self.assertIn("doporučuje Zastupitelstvu města Litovel", resolution_seo(record)["description"])
        self.assertIn('id="bod-2"', render_resolution_content(record))

    def test_agenda_title_is_an_escaped_heading_separate_from_the_decision(self):
        record = {"id": "UR-28-1/26", "datum": "2026-11-12", "organ": "Rada města Litovel",
                  "agenda_title": 'Budoucnost školy <Nasobůrky> & "dotaz"',
                  "actions": ["projednává"], "subject": "soukromou školu", "items": []}
        content = render_resolution_content(record)
        self.assertIn('<h2 id="bod-programu">Budoucnost školy &lt;Nasobůrky&gt; &amp; &quot;dotaz&quot;</h2>', content)
        self.assertIn('<p id="predmet">projednává soukromou školu</p>', content)
        preview = render_resolution_preview(record)
        self.assertIn('class="usn-agenda-title"><strong>Budoucnost školy &lt;Nasobůrky&gt;', preview)
        self.assertIn('class="usn-snippet">soukromou školu</div>', preview)
        self.assertTrue(resolution_seo(record)["seo_title"].startswith(record["agenda_title"]))
        self.assertIn("projednává soukromou školu", resolution_seo(record)["description"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_resolution(record, root, {}, {})
            write_meeting_index("2026", "RM", "1", [(record["id"], "/detail/", record["subject"], record["actions"])],
                                {"organ": record["organ"], "datum": record["datum"]}, root, {record["id"]: record})
            detail = (root / "usneseni/2026/UR-28-1-26/index.html").read_text()
            meeting = (root / "usneseni/2026/RM-1/index.html").read_text()
        self.assertIn('<h2 id="bod-programu">', detail)
        self.assertIn('class="usn-agenda-title"', meeting)
        self.assertIn("&lt;Nasobůrky&gt;", meeting)

    def test_missing_or_empty_agenda_title_does_not_add_a_heading(self):
        for title in (None, "", "  "):
            record = {"id": "RM/1/1/2026", "agenda_title": title, "subject": "program schůze"}
            self.assertNotIn('id="bod-programu"', render_resolution_content(record))
            self.assertNotIn('class="usn-agenda-title"', render_resolution_preview(record))

    def test_seo_uses_actual_items_when_subject_is_missing(self):
        seo = resolution_seo({
            "id": "RM/2589/82/2026", "datum": "2026-10-22", "organ": "Rada města Litovel",
            "subject": None, "actions": ["bere na vědomí"], "items": [
                {"label": "a", "text": "bere na vědomí výroční zprávu školy Jungmannova"},
                {"label": "b", "text": "bere na vědomí výroční zprávu školy Vítězná"},
            ],
        })
        self.assertIn("výroční zprávu školy Jungmannova", seo["description"])
        self.assertIn("22. 10. 2026.", seo["description"])
        self.assertIn("výroční zprávu školy Jungmannova", seo["seo_title"])
        self.assertIn("RM/2589/82/2026", seo["seo_title"])
        self.assertIn("Litovel", seo["seo_title"])
        self.assertNotIn("None", seo["description"])
        self.assertLessEqual(len(seo["description"]), 160)

    def test_seo_preserves_negative_action_and_plain_text_punctuation(self):
        resolution = {
            "id": "RM/1/1/2026", "datum": "2026-01-08", "organ": "Rada města Litovel",
            "subject": 'prodej pozemku společnosti "A & B".\nDruhá věta.',
            "actions": ["neschvaluje"], "items": [],
        }
        seo = resolution_seo(resolution)
        self.assertIn('neschvaluje prodej pozemku společnosti "A & B"', seo["description"])
        self.assertTrue(seo["seo_title"].startswith("neschvaluje"))
        self.assertNotIn("&amp;", seo["description"])
        self.assertNotIn("\n", seo["description"])
        with tempfile.TemporaryDirectory() as tmp:
            write_resolution(resolution, Path(tmp), {}, {})
            text = (Path(tmp) / "usneseni/2026/RM-1-1-2026/index.html").read_text()
        self.assertIn('<script src="/usneseni/back-link.js" defer></script>', text)
        self.assertNotIn("<script>", text)
        values = dict(line.split(": ", 1) for line in text.split("---")[1].strip().splitlines())
        self.assertEqual(json.loads(values["description"]), seo["description"])
        self.assertEqual(json.loads(values["seo_title"]), seo["seo_title"])

    def test_seo_tail_and_empty_document_have_safe_fallbacks(self):
        base = {"id": "ZM/1/1/2026", "datum": "2026-01-01", "organ": "Zastupitelstvo města Litovel"}
        self.assertIn("Dovětek", resolution_seo({**base, "tail": "Dovětek"})["seo_title"])
        seo = resolution_seo(base)
        self.assertNotIn("None", seo["seo_title"])
        self.assertIn(base["id"], seo["description"])

    def test_detail_anchors_preserve_original_indices_and_duplicate_labels(self):
        text = render_resolution_content({
            "id": "RM/1/1/2026", "subject": "Společný předmět", "tail": "Dovětek", "items": [
                {"label": "a", "text": "První bod"},
                {"label": "a", "text": "Druhý bod"},
            ],
        })
        self.assertIn('<p id="predmet">Společný předmět</p>', text)
        self.assertIn('<p id="bod-1"><strong>a)</strong> První bod</p>', text)
        self.assertIn('<p id="bod-2"><strong>a)</strong> Druhý bod</p>', text)
        self.assertIn('<p id="dovetek">Dovětek</p>', text)

    def test_single_action_subject_keeps_its_anchor(self):
        text = render_resolution_content({
            "id": "RM/1/1/2026", "actions": ["schvaluje"], "subject": "program schůze", "items": [],
        })
        self.assertIn('<p id="predmet">schvaluje program schůze</p>', text)

    def test_preview_preserves_subject_and_single_labelled_item(self):
        text = render_resolution_preview({
            "actions": ["schvaluje"], "subject": "Změny programu", "items": [
                {"label": "a", "text": "schvaluje doplnění programu"},
            ],
        })
        self.assertIn('class="usn-summary">schvaluje</div>', text)
        self.assertIn('class="usn-snippet">schvaluje Změny programu</div>', text)
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
