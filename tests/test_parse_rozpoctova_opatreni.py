import unittest
from pathlib import Path
from unittest.mock import patch

from parse_rozpoctova_opatreni import clean_description, parse_opatreni


class ParseRozpoctovaOpatreniTest(unittest.TestCase):
    def test_approval_header_preserves_both_official_resolution_id_formats(self):
        text = ("Rozpočtové opatření č. 1/2026 schválené Radou města Litovel\n"
                "Rozpočtové opatření bylo schváleno na 1. schůzi Rady města Litovel "
                "dne 2. 11. 2026 na základě usnesení UR-001-01/26 a RM/1/1/2026.\n")
        with patch("parse_rozpoctova_opatreni.pdf_to_text", return_value=text):
            record = parse_opatreni(Path("approval.pdf"))
        self.assertEqual(record["source_resolutions"], ["UR-001-01/26", "RM/1/1/2026"])

    def test_clean_description_strips_embedded_pdf_footer_and_table_header(self):
        value = (
            ") IČO: 00299138 ID datové schránky: 4rub4s3 Email: sekretariat@mestolitovel.cz "
            "Obec Cholina-dar na provoz pošty (RZ 13/2022/RM"
        )
        self.assertEqual(
            clean_description(value),
            "Obec Cholina-dar na provoz pošty (RZ 13/2022/RM",
        )

        header_value = "§ POL UZ ORJ ORG Kč Finanční příspěvek na výkon agendy SPOD (RZ 1/2022/RM)"
        self.assertEqual(
            clean_description(header_value),
            "Finanční příspěvek na výkon agendy SPOD (RZ 1/2022/RM",
        )

    def test_parse_older_ro_pdf_does_not_leak_city_footer_into_row_description(self):
        pdf_path = Path("resources/rozpoctova-opatreni/rozpoctove_opatreni_c._1_2022_schvalene_radou_mesta_litovel_dne_27._ledna_2022.pdf")
        opatreni = parse_opatreni(pdf_path)

        notes_by_title = {note["title"]: note["text"] for note in opatreni.get("notes", [])}
        self.assertIn("Rozpočtová změna č. 13/2022/RM", notes_by_title)
        self.assertIn(
            "Město Litovel poskytlo dar Obci Cholina na provoz Pošty Partner v Cholině v roce 2022.",
            notes_by_title["Rozpočtová změna č. 13/2022/RM"],
        )

        rows_13 = [
            row
            for section in opatreni["sections"]
            for row in section["rows"]
            if row.get("budget_change_id") == "13/2022/RM"
        ]
        descriptions_13 = [row.get("description") or "" for row in rows_13]

        self.assertTrue(any("Obec Cholina-dar na provoz pošty" in value for value in descriptions_13))
        self.assertFalse(any("IČO:" in value or "sekretariat@mestolitovel.cz" in value for value in descriptions_13))

        income_rows_1 = [
            row
            for section in opatreni["sections"]
            if section.get("type") == "prijmy"
            for row in section["rows"]
            if row.get("budget_change_id") == "1/2022/RM"
        ]
        self.assertEqual(len(income_rows_1), 1)
        self.assertEqual(income_rows_1[0]["amount"], "216 000,00")

    def test_parse_modern_ro_pdf_does_not_leak_footer_variant_into_row_description(self):
        pdf_path = Path("resources/rozpoctova-opatreni/rozpoctove_opatreni_c._7_2026_dne_2._dubna_2026.pdf")
        opatreni = parse_opatreni(pdf_path)

        rows_76 = [
            row
            for section in opatreni["sections"]
            for row in section["rows"]
            if row.get("budget_change_id") == "76/2026/RM"
        ]
        descriptions_76 = [row.get("description") or "" for row in rows_76]

        self.assertTrue(
            any(
                "KŘ - převod a aktualizace digitálního povodňového plánu - město Litovel a ORP Litovel" in value
                for value in descriptions_76
            )
        )
        self.assertFalse(
            any(
                "ID datové schránky:" in value or "sekretariat@mestolitovel.cz" in value
                for value in descriptions_76
            )
        )


if __name__ == "__main__":
    unittest.main()
