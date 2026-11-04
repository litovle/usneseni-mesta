import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from static_export.relationships import point_anchor, reference_parts, render_decision_history, render_later_revocations
from static_export.usneseni import render_resolution_preview, truncate_preview


def decision(rid, date, **kwargs):
    return {"id": rid, "datum": date, "organ": "Rada města Litovel", "actions": [], "items": [], **kwargs}


class DecisionRelationshipsTest(unittest.TestCase):
    def setUp(self):
        self.original = decision("RM/1/1/2025", "2025-01-10", items=[
            {"label": "a", "text": "schvaluje program"}, {"label": "b", "text": "schvaluje smlouvu"}])
        self.other = decision("RM/2/1/2025", "2025-01-10", subject="Zahrada <města>")
        self.change = decision("RM/3/2/2026", "2026-02-10", actions=["revokuje", "schvaluje"], items=[
            {"label": "a", "text": "revokuje usnesení RM/1/1/2025 v rozsahu bodu ad b)."},
            {"label": "b", "text": "schvaluje smlouvu navazující na RM/2/1/2025."}], references_out=[
            {"raw": "RM/1/1/2025", "resolved": self.original["id"]},
            {"raw": "RM/2/1/2025", "resolved": self.other["id"]}])
        self.records = {r["id"]: r for r in [self.original, self.other, self.change]}

    def test_revocation_must_reference_target_in_the_actual_revoking_point(self):
        parts = reference_parts(self.change, self.original["id"], revocations_only=True)
        self.assertEqual([(p["anchor"], p["target_label"]) for p in parts], [("bod-1", "b")])
        self.assertEqual(reference_parts(self.change, self.other["id"], revocations_only=True), [])
        self.assertEqual(reference_parts(self.change, self.other["id"])[0]["anchor"], "bod-2")
        self.assertEqual(reference_parts({**self.change, "items": [{"text": "schvaluje návrh, který revokuje RM/1/1/2025"}]}, self.original["id"], True), [])

    def test_implicit_reference_with_year_suffix_preserves_source_anchor(self):
        source = decision("RM/4/2/2026", "2026-02-10", actions=["revokuje"],
                          subject="usnesení č. 1/1/2025 v rozsahu bodu ad b).", references_out=[
                              {"raw": "1/1", "resolved": self.original["id"]}])
        part = reference_parts(source, self.original["id"], True)[0]
        self.assertEqual((part["anchor"], part["target_label"]), ("predmet", "b"))
        self.assertTrue(part["text"].startswith("revokuje "))

    def test_explicit_point_variants_and_duplicate_target_labels(self):
        for suffix, label in [("/b.", "b"), (" pod bodem a). Zbývající část pod bodem b) zůstává v platnosti.", "a"), (", odstavec b),", "b")]:
            source = {**self.change, "items": [{"label": "x", "text": "revokuje RM/1/1/2025" + suffix}]}
            part = reference_parts(source, self.original["id"], True)[0]
            self.assertEqual(part["target_label"], label)
            self.assertEqual(point_anchor(self.original, label), "bod-1" if label == "a" else "bod-2")
        duplicate = {**self.original, "items": [{"label": "a"}, {"label": "a"}]}
        self.assertEqual(point_anchor(duplicate, "a"), "")

    def test_notice_quotes_scope_and_links_source_and_original_points(self):
        html = render_later_revocations(self.original, [self.change["id"]], self.records, truncate_preview)
        self.assertIn("Pozdější revokace", html)
        self.assertIn('/usneseni/2026/RM-3-2-2026/#bod-1', html)
        self.assertIn('href="#bod-2"', html)
        self.assertIn("v rozsahu bodu ad b).", html)
        self.assertIn('datetime="2026-02-10"', html)
        self.assertNotIn("neplatné", html)
        self.assertEqual(render_later_revocations(self.other, [self.change["id"]], self.records, truncate_preview), "")
        older = {**self.change, "datum": "2024-01-01"}
        self.assertEqual(render_later_revocations(self.original, [older["id"]], {**self.records, older["id"]: older}, truncate_preview), "")

    def test_history_is_chronological_with_previews_and_a_current_marker(self):
        html = render_decision_history(self.original, [], [self.change["id"]], self.records, render_resolution_preview)
        self.assertLess(html.index('class="usn-head"><strong>RM/1/1/2025'), html.index('class="usn-head"><strong>RM/3/2/2026'))
        self.assertIn('aria-current="true"', html)
        self.assertIn("Právě čtete", html)
        self.assertIn("Obsahuje revokaci", html)
        self.assertIn("schvaluje smlouvu navazující", html)
        self.assertIn('/RM-3-2-2026/#bod-1', html)
        reverse = render_decision_history(self.change, [self.original["id"], self.other["id"]], [], self.records, render_resolution_preview)
        self.assertIn('/RM-1-1-2025/#bod-2', reverse)
        self.assertIn("Zahrada &lt;města&gt;", reverse)
        self.assertNotIn("Zahrada <města>", reverse)

    def test_unavailable_references_are_plain_text_without_broken_links(self):
        html = render_decision_history(self.original, ["RM/99/1/2019", "https://example.com", self.original["id"]], [], self.records, render_resolution_preview)
        self.assertIn("RM/99/1/2019", html)
        self.assertIn("text zatím není dostupný", html)
        self.assertNotIn('href="/usneseni/2019', html)
        self.assertNotIn("https://example.com", html)
        self.assertEqual(render_decision_history(self.original, [], [], self.records, render_resolution_preview), "")

    def test_cli_exports_both_directions_without_mislabeling_other_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resolutions.json"
            source.write_text(json.dumps(list(self.records.values()), ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "phase5_static_export.py"),
                            "--input", str(source), "--output", str(root / "output"), "--without-budget"],
                           check=True, capture_output=True, text=True)
            original = (root / "output/usneseni/2025/RM-1-1-2025/index.html").read_text()
            other = (root / "output/usneseni/2025/RM-2-1-2025/index.html").read_text()
            change = (root / "output/usneseni/2026/RM-3-2-2026/index.html").read_text()
        self.assertIn('class="usn-revision-notice"', original)
        self.assertLess(original.index('class="usn-revision-notice"'), original.index('<p id="bod-1">'))
        self.assertNotIn('class="usn-revision-notice"', other)
        self.assertIn('/RM-3-2-2026/#bod-2', other)
        self.assertIn('/RM-1-1-2025/#bod-2', change)
        self.assertNotIn("Je odkazováno z", original)


if __name__ == "__main__":
    unittest.main()
