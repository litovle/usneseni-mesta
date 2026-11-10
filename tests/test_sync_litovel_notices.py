import tempfile
import unittest
from pathlib import Path

from tools.sync_litovel_notices import (
    Attachment,
    Notice,
    budget_filename,
    existing_budget_keys,
    existing_resolution_keys,
    fetch_text,
    parse_attachments,
    parse_notice_board,
    parse_resolution_key,
    target_filename,
)


NOTICE_BOARD_HTML = """
<table class="uredni_deska_vypis">
  <tr>
    <th>Číslo jednací</th><th>Vyvěšení</th><th>Název</th><th>Zdroj</th><th>Typ</th>
  </tr>
  <tr>
    <td></td>
    <td class="nowrap">26.5.2026-31.12.2026</td>
    <td>
      <a href="/redakce/index.php?detail_claim=288585&amp;">Rozpočtové opatření č. 9/2026 schválené Radou města Litovel dne 14. května 2026</a>
    </td>
    <td>MěÚ Litovel - Finanční odbor</td>
    <td>-----</td>
  </tr>
  <tr>
    <td>RM/2271/73/2026</td>
    <td class="nowrap">22.5.2026-19.6.2026</td>
    <td>
      <a href="/redakce/index.php?detail_claim=288382&amp;">Výpis usnesení ze 73. schůze Rady města Litovel, konané dne 14. května 2026</a>
    </td>
    <td>MěÚ Litovel - Kancelář tajemníka</td>
    <td>Výpis z usnesení</td>
  </tr>
  <tr>
    <td>ZM/1/26/2026</td>
    <td class="nowrap">16.6.2026-16.7.2026</td>
    <td>
      <a href="/redakce/index.php?detail_claim=290917&amp;">Usnesení z 26. zasedání Zastupitelstva města Litovel ze dne 4.6.2026</a>
    </td>
    <td>MěÚ Litovel - Kancelář tajemníka</td>
    <td>-----</td>
  </tr>
  <tr>
    <td>31Nc 1901/2026</td>
    <td class="nowrap">30.4.2026-1.6.2026</td>
    <td><a href="/redakce/index.php?detail_claim=285701&amp;">Usnesení, veřejná vyhláška, o určení data smrti</a></td>
    <td>Okresní soud</td>
    <td>Veřejná vyhláška</td>
  </tr>
</table>
"""


DETAIL_HTML = """
<h3 class="oznameni_nazev">Rozpočtové opatření č. 9/2026</h3>
<ul>
  <li>
    <a href="https://www.litovel.eu/filemanager/files/file.php?file=5053287" title="*.pdf, 259.6 KB">
      <img src="/filemanager/icons/pdf.gif" alt="ikona souboru" />
      Rozpočtové opatření č  9 2026 dne  14  května 2026
    </a>
  </li>
  <li><a href="/cs/urad/">not a pdf</a></li>
</ul>
"""


class SyncLitovelNoticesTest(unittest.TestCase):
    def test_usneseni_cz_numbers_and_numbered_notice_titles_identify_the_meeting(self):
        cases = {
            "UZ-1-1/26": "ZM/1/2026",
            "UR-12-2/2026": "RM/2/2026",
            "Výpis usnesení č.1/2026 ze Zastupitelstva města Litovel": "ZM/1/2026",
            "Schválená usnesení z jednání č.2/2026 Rady města Litovel": "RM/2/2026",
            "vypis_usneseni_c.1_2026_ze_zastupitelstva_mesta_litovel.pdf": "ZM/1/2026",
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(parse_resolution_key(label), expected)

    def test_generic_numbered_attachment_does_not_guess_the_organ(self):
        self.assertIsNone(parse_resolution_key("Schválená usnesení z jednání č.1/2026"))

    def test_fetch_text_defaults_charsetless_html_to_utf8(self):
        class FakeResponse:
            headers = {"Content-Type": "text/html"}
            encoding = "ISO-8859-1"
            content = "Výpis usnesení ze 75. schůze".encode("utf-8")

            def raise_for_status(self):
                pass

            @property
            def text(self):
                return self.content.decode(self.encoding)

        class FakeSession:
            def get(self, url, timeout):
                return FakeResponse()

        self.assertEqual(
            fetch_text(FakeSession(), "https://www.litovel.eu/cs/urad/uredni-deska/aktualni-oznameni.html"),
            "Výpis usnesení ze 75. schůze",
        )

    def test_parse_notice_board_keeps_only_resolution_and_budget_rows(self):
        notices = parse_notice_board(NOTICE_BOARD_HTML, "https://www.litovel.eu/cs/urad/uredni-deska/aktualni-oznameni.html")

        self.assertEqual([notice.kind for notice in notices], ["budget_change", "resolution", "resolution"])
        self.assertEqual([notice.key for notice in notices], ["RO/9/2026", "RM/73/2026", "ZM/26/2026"])
        self.assertEqual(
            notices[0].detail_url,
            "https://www.litovel.eu/redakce/index.php?detail_claim=288585&",
        )

    def test_parse_attachments_accepts_filemanager_pdf_links(self):
        attachments = parse_attachments(DETAIL_HTML, "https://www.litovel.eu/redakce/index.php?detail_claim=288585&")

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].url, "https://www.litovel.eu/filemanager/files/file.php?file=5053287")
        self.assertEqual(attachments[0].label, "Rozpočtové opatření č 9 2026 dne 14 května 2026")

    def test_target_filename_uses_existing_budget_style_when_title_has_date(self):
        notice = Notice(
            kind="budget_change",
            key="RO/9/2026",
            title="Rozpočtové opatření č. 9/2026 schválené Radou města Litovel dne 14. května 2026",
            detail_url="https://example.test/detail",
            posted="",
            source="",
            notice_type="",
        )
        filename = target_filename(notice, parse_attachments(DETAIL_HTML, "https://example.test/detail")[0])

        self.assertEqual(filename, "rozpoctove_opatreni_c._9_2026_dne_14._kvetna_2026.pdf")

    def test_target_filename_uses_resolution_title_for_generic_attachment_label(self):
        notice = Notice(
            kind="resolution",
            key="RM/75/2026",
            title="Výpis usnesení ze 75. schůze Rady města Litovel, konané dne 10. června 2026",
            detail_url="https://example.test/detail",
            posted="",
            source="",
            notice_type="",
        )
        attachment = Attachment(url="https://example.test/file.pdf", label="Výpis usnesení")

        self.assertEqual(
            target_filename(notice, attachment),
            "vypis_usneseni_ze_75._schuze_rady_mesta_litovel_konane_dne_10._cervna_2026.pdf",
        )

    def test_budget_filename_handles_numeric_notice_dates(self):
        self.assertEqual(
            budget_filename(
                "Rozpočtové opatření č.4/2026 schválené Radou města Litovel dne 19.2. 2026",
                "",
            ),
            "rozpoctove_opatreni_c._4_2026_dne_19.2._2026.pdf",
        )

    def test_existing_keys_are_loaded_from_work_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "work" / "phase1").mkdir(parents=True)
            (root / "work" / "phase1" / "RM-2271-73-2026.json").write_text(
                '{"id": "RM/2271/73/2026"}',
                encoding="utf-8",
            )
            (root / "work" / "rozpoctova-opatreni").mkdir(parents=True)
            (root / "work" / "rozpoctova-opatreni" / "RO-9-2026.json").write_text(
                '{"id": "RO/9/2026"}',
                encoding="utf-8",
            )

            self.assertIn("RM/73/2026", existing_resolution_keys(root / "work", root / "resources"))
            self.assertIn(
                "RO/9/2026",
                existing_budget_keys(root / "work", root / "resources" / "rozpoctova-opatreni"),
            )


if __name__ == "__main__":
    unittest.main()
