import tempfile
import unittest
from pathlib import Path

from phase2_resolution_analysis import extract_action, process_usneseni
from phase3_resolve_references import process_resolutions
from static_export.usneseni import write_resolution


def raw(rid, date, text):
    return {"id": rid, "datum": date, "text_raw": "Rada města Litovel " + text}


class SubjectReferenceTest(unittest.TestCase):
    def test_rm_2592_change_action_and_reference_are_detected(self):
        record = process_usneseni(raw("RM/2592/82/2026", "2026-10-22",
            "mění usnesení č. RM/2563/81/2026 ze dne 1. 10. 2026 tak, že se částka „1.800.000 Kč včetně\n"
            "DPH“ nahrazuje částkou „2.000.000 Kč včetně DPH“. Ostatní části usnesení zůstávají beze změny."))
        self.assertEqual(record["references_out"], [{"raw": "RM/2563/81/2026", "type": "explicit", "resolved": "RM/2563/81/2026"}])
        self.assertEqual(record["actions"], ["mění"])
        self.assertTrue(record["subject"].startswith("usnesení"))
        self.assertEqual(record["amounts"], ["1.800.000 Kč", "2.000.000 Kč"])

    def test_unrecognized_action_still_extracts_subject_references(self):
        record = process_usneseni(raw("RM/20/2/2026", "2026-02-01", "upravuje usnesení RM/19/1/2026."))
        self.assertEqual(record["references_out"][0]["resolved"], "RM/19/1/2026")
        self.assertTrue(record["subject"].startswith("upravuje"))

    def test_meni_in_a_labelled_point_and_negated_action(self):
        record = process_usneseni(raw("RM/20/2/2026", "2026-02-01",
            "\na) mění usnesení RM/19/1/2026.\nb) souhlasí s nákupem."))
        self.assertIn("mění", record["actions"])
        self.assertEqual(record["items"][0]["label"], "a")
        self.assertEqual(record["references_out"][0]["resolved"], "RM/19/1/2026")
        self.assertEqual(extract_action("nemění podmínky smlouvy"), "nemění")
        self.assertIsNone(extract_action("změnila podmínky smlouvy"))

    def test_subject_supports_explicit_and_implicit_references(self):
        record = process_usneseni(raw("RM/20/2/2026", "2026-02-01",
            "revokuje usnesení RM/19/1/2026 a usnesení č. 18/1."))
        self.assertEqual(record["actions"], ["revokuje"])
        self.assertEqual([ref["raw"] for ref in record["references_out"]], ["RM/19/1/2026", "18/1"])

    def test_repeated_subject_and_item_references_are_deduplicated(self):
        record = process_usneseni(raw("RM/20/2/2026", "2026-02-01",
            "schvaluje doplnění usnesení RM/19/1/2026:\na) doplnění smlouvy z usnesení RM/19/1/2026."))
        self.assertEqual(len(record["references_out"]), 1)
        self.assertEqual(record["items"][0]["label"], "a")

    def test_subject_reference_reaches_both_static_pages(self):
        source = process_usneseni(raw("RM/2592/82/2026", "2026-10-22",
            "mění usnesení č. RM/2563/81/2026: částka 1.800.000 Kč se nahrazuje částkou 2.000.000 Kč."))
        target = process_usneseni(raw("RM/2563/81/2026", "2026-10-01", "souhlasí s pořízením strojního vybavení."))
        records, _, _ = process_resolutions([source, target], terms=[])
        byid = {r["id"]: r for r in records}
        self.assertEqual(byid[target["id"]]["references_in"][0]["from"], source["id"])
        outgoing = {source["id"]: [target["id"]]}
        incoming = {target["id"]: [source["id"]]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for record in records:
                write_resolution(record, root, outgoing, incoming, byid)
            source_html = (root / "usneseni/2026/RM-2592-82-2026/index.html").read_text()
            target_html = (root / "usneseni/2026/RM-2563-81-2026/index.html").read_text()
        self.assertIn('href="/usneseni/2026/RM-2563-81-2026/"', source_html)
        self.assertIn('href="/usneseni/2026/RM-2592-82-2026/#predmet"', target_html)
        self.assertIn("Vývoj rozhodnutí", source_html)
        self.assertNotIn('class="usn-revision-notice"', target_html)


if __name__ == "__main__":
    unittest.main()
