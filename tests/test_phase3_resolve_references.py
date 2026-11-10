import unittest

from election_terms import term_for_date
from phase2_resolution_analysis import extract_refs
from phase3_resolve_references import process_resolutions


def resolution(resolution_id, datum, refs=None, organ="Rada města Litovel"):
    return {
        "id": resolution_id,
        "datum": datum,
        "organ": organ,
        "actions": ["schvaluje"],
        "references_out": refs or [],
    }


class Phase3ResolveReferencesTest(unittest.TestCase):
    def test_references_connect_existing_and_native_records_in_both_directions(self):
        older = resolution("RM/1/82/2026", "2026-10-22")
        native = resolution("UR-001-01/26", "2026-11-02", extract_refs("mění RM/1/82/2026"))
        later = resolution("RM/2/83/2026", "2026-11-03", extract_refs("mění UR-001-01/26"))
        records, refs, stats = process_resolutions([older, native, later], terms=[])
        self.assertEqual(records[0]["references_in"][0]["from"], "UR-001-01/26")
        self.assertEqual(records[1]["references_in"][0]["from"], "RM/2/83/2026")
        self.assertEqual(refs[(native["id"], older["id"])], older["id"])
        self.assertEqual(refs[(later["id"], native["id"])], native["id"])

    def test_explicit_native_ids_are_not_aliases_of_other_records(self):
        source = resolution("UZ-2-1/26", "2026-11-02", [{"raw": "UZ-1-1/26", "type": "explicit", "resolved": None}])
        records, refs, stats = process_resolutions([
            resolution("ZM/1/1/2026", "2026-11-02"), resolution("UZ-1-1/26", "2026-11-02"), source
        ], terms=[])
        self.assertEqual(len({record["id"] for record in records}), 3)
        self.assertEqual(refs[(source["id"], "UZ-1-1/26")], "UZ-1-1/26")
        self.assertEqual(records[0]["references_in"], [])
        self.assertEqual(records[1]["references_in"][0]["from"], "UZ-2-1/26")

    def test_ambiguous_shorthand_does_not_choose_between_distinct_official_ids(self):
        source = resolution("UZ-2-1/26", "2026-11-03", [{"raw": "1/1", "type": "implicit", "resolved": None}], organ="Zastupitelstvo města Litovel")
        records, refs, stats = process_resolutions([
            resolution("ZM/1/1/2026", "2026-11-02"), resolution("UZ-1-1/26", "2026-11-02"), source
        ], terms=[])
        self.assertIsNone(records[2]["references_out"][0]["resolved"])
        self.assertEqual(stats["refs_ambiguous"], 1)

    def test_implicit_reference_ignores_future_reset_candidate(self):
        records = [
            resolution("RM/1/1/2022", "2022-10-27"),
            resolution(
                "RM/10/1/2022",
                "2022-10-27",
                [{"raw": "1/1", "type": "implicit", "resolved": None}],
            ),
            resolution("RM/1/1/2026", "2026-10-29"),
        ]

        processed, _refs_index, stats = process_resolutions(records, terms=[])
        by_id = {item["id"]: item for item in processed}

        self.assertEqual(stats["refs_resolved"], 1)
        self.assertEqual(
            by_id["RM/10/1/2022"]["references_out"][0]["resolved"],
            "RM/1/1/2022",
        )
        self.assertEqual(
            by_id["RM/1/1/2022"]["references_in"],
            [{"from": "RM/10/1/2022", "action": "schvaluje"}],
        )
        self.assertEqual(by_id["RM/1/1/2026"]["references_in"], [])

    def test_implicit_reference_stays_with_same_body(self):
        records = [
            resolution(
                "RM/2/1/2026",
                "2026-11-05",
                [{"raw": "1/1", "type": "implicit", "resolved": None}],
            ),
            resolution(
                "ZM/1/1/2026",
                "2026-10-29",
                organ="Zastupitelstvo města Litovel",
            ),
        ]

        processed, _refs_index, stats = process_resolutions(records, terms=[])
        by_id = {item["id"]: item for item in processed}

        self.assertEqual(stats["refs_resolved"], 0)
        self.assertEqual(stats["refs_unresolved"], 1)
        self.assertIsNone(by_id["RM/2/1/2026"]["references_out"][0]["resolved"])

    def test_term_for_date_uses_configured_boundaries(self):
        terms = [
            {"id": "old", "label": "Old term", "start": "2022-09-24", "end": "2026-10-10"},
            {"id": "new", "label": "New term", "start": "2026-10-10", "end": None},
        ]

        self.assertEqual(term_for_date("2026-10-09", terms)["id"], "old")
        self.assertEqual(term_for_date("2026-10-10", terms)["id"], "new")

    def test_extract_refs_detects_explicit_zm_references(self):
        refs = extract_refs("navazuje na ZM/6/23/2025 a RM/2139/69/2026")

        self.assertEqual(
            refs,
            [
                {"raw": "ZM/6/23/2025", "type": "explicit", "resolved": "ZM/6/23/2025"},
                {"raw": "RM/2139/69/2026", "type": "explicit", "resolved": "RM/2139/69/2026"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
