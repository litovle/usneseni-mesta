import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from static_export.inline_refs import render_inline_refs
from static_export.usneseni import render_resolution_content, write_resolution


class PlainText(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.feed(html)

    def handle_data(self, data):
        self.text.append(data)


def reference(raw="RM/2563/81/2026", target="RM/2563/81/2026"):
    return {"raw": raw, "resolved": target}


class InlineReferencesTest(unittest.TestCase):
    def setUp(self):
        self.records = {"RM/2563/81/2026": {}, "ZM/1/1/2025": {}, "RM/1930/63/2025": {}}

    def test_explicit_references_repeat_without_changing_text_or_escaping(self):
        text = 'mění RM/2563/81/2026 & ZM/1/1/2025, dále RM/2563/81/2026. <img src=x>'
        html = render_inline_refs(text, {"references_out": [reference(), reference(), reference("ZM/1/1/2025", "ZM/1/1/2025")]}, self.records)
        self.assertEqual(html.count('class="usn-inline-ref usn-context-link"'), 3)
        self.assertEqual("".join(PlainText(html).text), text)
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertNotIn("<img", html)

    def test_resolved_shorthand_links_the_recorded_year_without_matching_other_numbers(self):
        text = "usnesení 1930/63, dále 1930/63/2025. Čísla 1930/630 a 11930/63 zůstávají textem."
        html = render_inline_refs(text, {"references_out": [reference("1930/63", "RM/1930/63/2025")]}, self.records)
        self.assertEqual(html.count('href="/usneseni/2025/RM-1930-63-2025/"'), 2)
        self.assertIn('>1930/63/2025</a>', html)
        self.assertEqual("".join(PlainText(html).text), text)

    def test_unknown_ambiguous_and_invalid_targets_remain_plain_text(self):
        text = "RM/2563/81/2026 a 1930/63 a ZM/1/1/2025"
        refs = [reference(), reference("1930/63", "RM/1930/63/2025"),
                reference("1930/63", "RM/1930/63/2024"), reference("ZM/1/1/2025", "https://example.com")]
        html = render_inline_refs(text, {"references_out": refs}, {"RM/1930/63/2025": {}})
        self.assertEqual(html, text)
        self.assertEqual(render_inline_refs(text, {"references_out": refs}, None), text)

    def test_wrapped_ids_and_point_suffixes_preserve_the_original_spelling(self):
        text = "RM / 2563 / 81 /\n2026 a ZM/1/1/2025/b."
        html = render_inline_refs(text, {"references_out": [reference(), reference("ZM/1/1/2025", "ZM/1/1/2025")]}, self.records)
        self.assertEqual(html.count('class="usn-inline-ref usn-context-link"'), 2)
        self.assertIn('>ZM/1/1/2025</a>/b.', html)
        self.assertEqual("".join(PlainText(html).text), text)
        shorthand = render_inline_refs("1930/63ah.", {"references_out": [reference("1930/63", "RM/1930/63/2025")]}, self.records)
        self.assertIn('>1930/63</a>ah.', shorthand)

    def test_reference_prefixes_inside_longer_ids_are_not_linked(self):
        text = "RM/2563/81/20260 RM/2563/81/2026/12 ZM/1/1/20250"
        html = render_inline_refs(text, {"references_out": [reference(), reference("ZM/1/1/2025", "ZM/1/1/2025")]}, self.records)
        self.assertEqual(html, text)

    def test_subject_items_and_tail_link_only_documented_references(self):
        record = {"id": "RM/2592/82/2026", "subject": "mění RM/2563/81/2026", "items": [
            {"label": "a", "text": "odkazuje na ZM/1/1/2025 a RM/99/1/2025"}],
            "tail": "Dále RM/2563/81/2026.", "references_out": [reference(), reference("ZM/1/1/2025", "ZM/1/1/2025")]}
        html = render_resolution_content(record, self.records)
        self.assertEqual(html.count('class="usn-inline-ref usn-context-link"'), 3)
        self.assertIn('<p id="bod-1"><strong>a)</strong>', html)
        self.assertNotIn('href="/usneseni/2025/RM-99-1-2025/', html)

    def test_write_resolution_links_rm_2592_and_keeps_original_text(self):
        record = {"id": "RM/2592/82/2026", "datum": "2026-10-22", "organ": "Rada města Litovel", "actions": ["mění"],
                  "subject": "usnesení č. RM/2563/81/2026: částka 1.800.000 Kč se nahrazuje částkou 2.000.000 Kč.",
                  "items": [], "references_out": [reference()]}
        records = {**self.records, record["id"]: record}
        records["RM/2563/81/2026"] = {"id": "RM/2563/81/2026", "datum": "2026-10-01", "subject": "nákup vybavení"}
        before = render_resolution_content(record)
        after = render_resolution_content(record, records)
        self.assertEqual("".join(PlainText(before).text), "".join(PlainText(after).text))
        with tempfile.TemporaryDirectory() as directory:
            write_resolution(record, Path(directory), {record["id"]: ["RM/2563/81/2026"]}, {}, records)
            page = (Path(directory) / "usneseni/2026/RM-2592-82-2026/index.html").read_text()
        self.assertIn('<p id="predmet">mění usnesení č. <a class="usn-inline-ref usn-context-link" href="/usneseni/2026/RM-2563-81-2026/">RM/2563/81/2026</a>', page)


if __name__ == "__main__":
    unittest.main()
