import unittest

from crosslink_rozpoctova_opatreni import (
    build_budget_change_index,
    crosslink,
    extract_budget_change_mentions,
    resolve_resolution_id,
)


class CrosslinkRozpoctovaOpatreniTest(unittest.TestCase):
    def test_native_ids_are_linked_exactly_without_translating_them(self):
        by_id = {"UR-1-1/26": {}, "RM/1/1/2026": {}}
        by_key = {("RM", 1, 1): list(by_id)}
        self.assertEqual(resolve_resolution_id("UR-1-1/26", by_id, by_key), ("UR-1-1/26", None))
        self.assertEqual(resolve_resolution_id("UR-1-1/2026", by_id, by_key), (None, None))
        self.assertEqual(resolve_resolution_id("RM/1/1/2025", {"UR-1-1/26": {}}, {("RM", 1, 1): ["UR-1-1/26"]}), (None, None))

    def test_extracts_direct_and_range_budget_change_ids(self):
        known = {
            "53/2026/RM",
            "54/2026/RM",
            "55/2026/RM",
            "60/2026/RM",
            "194/2025/RM",
        }

        mentions = extract_budget_change_mentions(
            "schvaluje rozpočtové změny 53/2026/RM až 60/2026/RM a RZ 194/2025/RM",
            known,
        )

        self.assertEqual(mentions["53/2026/RM"], "range")
        self.assertEqual(mentions["54/2026/RM"], "range")
        self.assertEqual(mentions["55/2026/RM"], "range")
        self.assertEqual(mentions["60/2026/RM"], "range")
        self.assertEqual(mentions["194/2025/RM"], "direct")

    def test_ignores_city_directive_number_that_looks_like_budget_change_id(self):
        mentions = extract_budget_change_mentions(
            "souhlasí s výběrem dodavatele automatického WC modulu typu CWC R110 "
            "v režimu výjimky ze směrnice RM č. 1/2025/RM čl. 4 odst. 3.",
            {"1/2025/RM"},
        )

        self.assertEqual(mentions, {})

    def test_resolves_unique_year_typo(self):
        by_id = {
            "RM/2139/69/2026": {},
        }
        by_key = {
            ("RM", 2139, 69): ["RM/2139/69/2026"],
        }

        resolved, correction = resolve_resolution_id(
            "RM/2139/69/2016",
            by_id,
            by_key,
        )

        self.assertEqual(resolved, "RM/2139/69/2026")
        self.assertEqual(correction["raw"], "RM/2139/69/2016")

    def test_crosslink_adds_bidirectional_links(self):
        resolutions = [
            {
                "id": "RM/2161/69/2026",
                "subject": "schvaluje rozpočtové změny 53/2026/RM až 54/2026/RM",
                "items": [],
                "tail": None,
            },
            {
                "id": "RM/2139/69/2026",
                "subject": None,
                "items": [],
                "tail": None,
            },
        ]
        opatreni = [
            {
                "id": "RO/6/2026",
                "source_resolutions": ["RM/2139/69/2016", "RM/2161/69/2026"],
                "sections": [
                    {
                        "type": "vydaje",
                        "rows": [
                            {
                                "budget_change_id": "53/2026/RM",
                                "amount": "1 000,00",
                                "amount_value": 1000.0,
                                "description": "ZŠ Jungmannova - oprava učebny",
                            },
                            {
                                "budget_change_id": "54/2026/RM",
                                "amount": "2 000,00",
                                "amount_value": 2000.0,
                                "description": "ČOV Litovel - servis čerpadla",
                            },
                        ],
                    },
                ],
            },
        ]

        linked_resolutions, linked_opatreni, index, stats = crosslink(resolutions, opatreni)
        by_resolution = {item["id"]: item for item in linked_resolutions}

        self.assertEqual(stats["approval_links"], 2)
        self.assertEqual(stats["budget_change_links"], 2)
        self.assertEqual(len(stats["corrected_source_resolutions"]), 1)
        self.assertEqual(
            by_resolution["RM/2161/69/2026"]["budget_change_links"][0]["budget_change_id"],
            "53/2026/RM",
        )
        self.assertEqual(
            by_resolution["RM/2161/69/2026"]["budget_change_links"][0]["plain_title"],
            "ZŠ Jungmannova - oprava učebny",
        )
        self.assertEqual(
            by_resolution["RM/2161/69/2026"]["budget_change_links"][0]["affected_place"],
            "ZŠ Jungmannova / oprava učebny",
        )
        self.assertEqual(
            by_resolution["RM/2139/69/2026"]["budget_opatreni_approved"],
            [{"opatreni_id": "RO/6/2026", "source": "ro_header"}],
        )
        self.assertEqual(index["53/2026/RM"]["resolution_ids"], ["RM/2161/69/2026"])
        self.assertEqual(index["53/2026/RM"]["plain_title"], "ZŠ Jungmannova - oprava učebny")
        self.assertEqual(index["53/2026/RM"]["affected_place"], "ZŠ Jungmannova / oprava učebny")
        self.assertEqual(
            linked_opatreni[0]["resolution_links"][-1],
            {
                "resolution_id": "RM/2161/69/2026",
                "relation": "mentions_budget_change",
                "budget_change_ids": ["53/2026/RM", "54/2026/RM"],
            },
        )

    def test_budget_change_index_uses_destination_title_for_expense_transfer(self):
        index = build_budget_change_index([
            {
                "id": "RO/7/2026",
                "sections": [
                    {
                        "type": "vydaje",
                        "rows": [
                            {
                                "budget_change_id": "77/2026/RM",
                                "amount": "-50 000,00",
                                "amount_value": -50000.0,
                                "description": "OŽP - zpracování PD k vynětí půdy (RZ 77/2026/RM)",
                            },
                            {
                                "budget_change_id": "77/2026/RM",
                                "amount": "50 000,00",
                                "amount_value": 50000.0,
                                "description": "svoz komunálního odpadu (RZ 77/2026/RM)",
                            },
                        ],
                    },
                ],
            }
        ])

        self.assertEqual(index["77/2026/RM"]["plain_title"], "svoz komunálního odpadu")


if __name__ == "__main__":
    unittest.main()
