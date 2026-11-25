import tempfile
import unittest
import requests
import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from tools.sync_litovel_notices import (
    Attachment,
    Notice,
    NOTICE_BOARD_URL,
    DYNAMIC_NOTICE_BOARD_URL,
    budget_filename,
    existing_budget_keys,
    existing_resolution_keys,
    fetch_text,
    fetch_notice_board,
    parse_attachments,
    parse_notice_board,
    parse_resolution_key,
    target_filename,
    sync_notices,
    main,
    write_manifest,
    write_pr_body,
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
    def test_cli_puts_a_failed_source_in_both_the_manifest_and_pr_body(self):
        def response(session, url):
            if url == NOTICE_BOARD_URL:
                raise requests.Timeout()
            return NOTICE_BOARD_HTML if url == DYNAMIC_NOTICE_BOARD_URL else DETAIL_HTML

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, body = root / "manifest.json", root / "body.md"
            argv = ["sync_litovel_notices.py", "--dry-run", "--resources", str(root / "resources"),
                    "--ro-pdf", str(root / "ro"), "--workdir", str(root / "work"),
                    "--manifest", str(manifest), "--pr-body", str(body)]
            with patch("sys.argv", argv), patch("tools.sync_litovel_notices.fetch_text", side_effect=response), \
                    patch("tools.sync_litovel_notices.write_github_output"), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            payload = json.loads(manifest.read_text())
            text = body.read_text()
        self.assertEqual(payload["notice_boards"][0],
                         {"url": NOTICE_BOARD_URL, "status": "failed", "error": "Timeout"})
        self.assertEqual(payload["notice_boards"][1]["status"], "ok")
        self.assertEqual(len(payload["downloaded"]), 3)
        self.assertIn("**Warning:**", text)
        self.assertIn(f"{NOTICE_BOARD_URL}: FAILED (Timeout)", text)
        self.assertIn(f"{DYNAMIC_NOTICE_BOARD_URL}: OK, 3 relevant notices", text)

    def test_pr_body_reports_different_documents_even_when_source_counts_match(self):
        reports = []
        newer = NOTICE_BOARD_HTML.replace("č. 9/2026", "č. 19/2026")
        with patch("tools.sync_litovel_notices.fetch_text", side_effect=[NOTICE_BOARD_HTML, newer]), \
                contextlib.redirect_stdout(io.StringIO()):
            fetch_notice_board(None, NOTICE_BOARD_URL, board_results=reports)
        with tempfile.TemporaryDirectory() as tmp:
            manifest, body = Path(tmp) / "manifest.json", Path(tmp) / "body.md"
            write_manifest(manifest, [], True, reports)
            write_pr_body(body, manifest, [], True)
            text = body.read_text()
        self.assertEqual([r["notice_count"] for r in reports], [3, 3])
        self.assertEqual(reports[0]["missing_keys"], ["RO/19/2026"])
        self.assertEqual(reports[1]["missing_keys"], ["RO/9/2026"])
        self.assertIn("Missing from this view compared with the combined results: `RO/19/2026`", text)
        self.assertIn("Missing from this view compared with the combined results: `RO/9/2026`", text)
        self.assertNotIn("FAILED", text)

    def test_primary_view_failure_uses_the_alternate_view(self):
        with patch("tools.sync_litovel_notices.fetch_text", side_effect=[requests.Timeout(), NOTICE_BOARD_HTML]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            notices = fetch_notice_board(None, NOTICE_BOARD_URL)
        self.assertEqual({n.key for n in notices}, {"RO/9/2026", "RM/73/2026", "ZM/26/2026"})
        self.assertIn("::warning::", output.getvalue())

    def test_successful_views_are_combined_without_duplicate_downloads(self):
        newer = NOTICE_BOARD_HTML.replace("č. 9/2026", "č. 19/2026")
        with patch("tools.sync_litovel_notices.fetch_text", side_effect=[NOTICE_BOARD_HTML, newer]) as fetch, \
                contextlib.redirect_stdout(io.StringIO()):
            notices = fetch_notice_board(None, NOTICE_BOARD_URL)
        self.assertEqual({n.key for n in notices}, {"RO/9/2026", "RO/19/2026", "RM/73/2026", "ZM/26/2026"})
        self.assertEqual(len(notices), 4)
        self.assertEqual([c.args[1] for c in fetch.call_args_list], [NOTICE_BOARD_URL, DYNAMIC_NOTICE_BOARD_URL])

    def test_http_200_without_a_board_is_not_treated_as_no_new_documents(self):
        with patch("tools.sync_litovel_notices.fetch_text", side_effect=["<html>Maintenance</html>", NOTICE_BOARD_HTML]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            notices = fetch_notice_board(None, NOTICE_BOARD_URL)
        self.assertEqual(len(notices), 3)
        self.assertIn("::warning::", output.getvalue())

    def test_unavailable_or_invalid_views_fail_instead_of_reporting_no_updates(self):
        for responses in ([requests.Timeout(), requests.ConnectionError()], ["<html>Error</html>"] * 2):
            with self.subTest(responses=responses), \
                    patch("tools.sync_litovel_notices.fetch_text", side_effect=responses), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaisesRegex(RuntimeError, "No readable notice-board table"):
                fetch_notice_board(None, NOTICE_BOARD_URL)

    def test_legitimate_empty_boards_remain_a_successful_scan(self):
        with patch("tools.sync_litovel_notices.fetch_text", return_value='<table class="uredni_deska_vypis"></table>'), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fetch_notice_board(None, NOTICE_BOARD_URL), [])

    def test_custom_notice_url_does_not_add_unrelated_sources(self):
        custom = "https://example.org/custom-board"
        with patch("tools.sync_litovel_notices.fetch_text", return_value=NOTICE_BOARD_HTML) as fetch, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(len(fetch_notice_board(None, custom)), 3)
        fetch.assert_called_once_with(None, custom)

    def test_default_scan_survives_one_official_view_being_unavailable(self):
        pretty_url = "https://www.litovel.eu/cs/urad/uredni-deska/aktualni-oznameni.html"

        def response(session, url):
            if url == pretty_url:
                return NOTICE_BOARD_HTML
            if "detail_claim=" in url:
                return DETAIL_HTML
            raise requests.Timeout("alternate view unavailable")

        with tempfile.TemporaryDirectory() as tmp, \
                patch("tools.sync_litovel_notices.fetch_text", side_effect=response):
            root = Path(tmp)
            found = sync_notices(notice_url=NOTICE_BOARD_URL, resources_dir=root / "resources",
                                 ro_dir=root / "ro", workdir=root / "work", dry_run=True)
        self.assertEqual({item.key for item in found}, {"RO/9/2026", "RM/73/2026", "ZM/26/2026"})

    def test_default_scan_finds_a_new_notice_missing_from_the_stale_pretty_url(self):
        current_url = "https://www.litovel.eu/redakce/index.php?clanek=47101&lanG=cs"
        current_html = """<table class="uredni_deska_vypis"><tr>
            <td></td><td>25.11.2026-31.12.2026</td>
            <td><a href="/redakce/index.php?detail_claim=307537">Rozpočtové opatření č.19/2026 schválené Radou města Litovel dne 12. listopadu 2026</a></td>
            <td>MěÚ Litovel</td><td>-----</td></tr></table>"""

        def response(session, url):
            if url == current_url:
                return current_html
            if "detail_claim=307537" in url:
                return DETAIL_HTML
            return '<table class="uredni_deska_vypis"></table>'

        with tempfile.TemporaryDirectory() as tmp, \
                patch("tools.sync_litovel_notices.fetch_text", side_effect=response):
            root = Path(tmp)
            found = sync_notices(notice_url=NOTICE_BOARD_URL, resources_dir=root / "resources",
                                 ro_dir=root / "ro", workdir=root / "work", dry_run=True)
        self.assertEqual([item.key for item in found], ["RO/19/2026"])

    def test_prefixed_numbers_and_numbered_notice_titles_identify_the_meeting(self):
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
