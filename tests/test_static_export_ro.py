import tempfile
import unittest
from pathlib import Path

from phase5_static_export import (
    group_opatreni_by_content_year,
    render_budget_links_section,
    ro_slug_from_id,
    rz_anchor,
    write_ro_index,
    write_sitemap,
    write_year_index,
    write_ro_page,
)
from parse_rozpoctova_opatreni import normalize_financing_sections
from static_export.ro_summary import (
    affected_place_service_from_title,
    aggregate_top_categories,
    summarize_affected_places,
    summarize_opatreni_plain,
)


class StaticExportRozpoctovaOpatreniTest(unittest.TestCase):
    def test_ro_slug_and_rz_anchor(self):
        self.assertEqual(ro_slug_from_id("RO/6/2026"), "RO-6-2026")
        self.assertEqual(rz_anchor("53/2026/RM"), "rz-53-2026-rm")

    def test_write_sitemap_uses_usneseni_filename_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            main_sitemap = output / "sitemap.xml"
            main_sitemap.write_text("main sitemap index", encoding="utf-8")

            write_sitemap(["/usneseni/2026/"], output)

            sitemap = output / "sitemap-usneseni.xml"
            self.assertTrue(sitemap.exists())
            self.assertEqual("main sitemap index", main_sitemap.read_text(encoding="utf-8"))
            self.assertIn(
                "<loc>https://litovle.cz/usneseni/2026/</loc>",
                sitemap.read_text(encoding="utf-8"),
            )

    def test_resolution_budget_links_point_to_ro_and_rz_anchor(self):
        html = render_budget_links_section({
            "budget_opatreni_approved": [
                {"opatreni_id": "RO/6/2026", "source": "ro_header"},
            ],
            "budget_change_links": [
                {
                    "budget_change_id": "53/2026/RM",
                    "opatreni_id": "RO/6/2026",
                    "plain_title": "přijaté pojistné plnění",
                    "source": "text",
                    "match": "range",
                },
            ],
        })

        self.assertIn('/rozpoctova-opatreni/RO-6-2026/', html)
        self.assertIn('/rozpoctova-opatreni/RO-6-2026/#rz-53-2026-rm', html)
        self.assertIn('<h3>Odkazováno z rozpočtového opatření</h3>', html)
        self.assertIn('<h3>Zmiňuje rozpočtové změny</h3>', html)
        self.assertIn('Rozpočtová změna 53/2026/RM: přijaté pojistné plnění', html)

    def test_resolution_budget_links_include_affected_place_when_title_is_generic(self):
        html = render_budget_links_section({
            "budget_opatreni_approved": [],
            "budget_change_links": [
                {
                    "budget_change_id": "80/2026/RM",
                    "opatreni_id": "RO/7/2026",
                    "plain_title": "renovace vnitřních prostor",
                    "affected_place": "Unčovice / Sokolovna",
                    "source": "text",
                    "match": "direct",
                },
            ],
        })

        self.assertIn(
            'Rozpočtová změna 80/2026/RM: renovace vnitřních prostor (Unčovice / Sokolovna)',
            html,
        )

    def test_write_ro_page_contains_rz_anchor_and_resolution_link(self):
        opatreni = {
            "id": "RO/6/2026",
            "approval_date": "2026-03-12",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 69, "type": "schůzi", "date": "2026-03-12"},
            "budget_change_ids": ["53/2026/RM"],
            "resolution_links": [
                {
                    "resolution_id": "RM/2161/69/2026",
                    "relation": "approves_opatreni",
                    "source": "ro_header",
                },
                {
                    "resolution_id": "RM/2161/69/2026",
                    "relation": "mentions_budget_change",
                    "budget_change_ids": ["53/2026/RM"],
                },
            ],
            "sections": [
                {
                    "type": "prijmy",
                    "rows": [
                        {
                            "budget_change_id": "53/2026/RM",
                            "raw_codes": ["6320", "2322"],
                            "amount": "3 645,00",
                            "amount_value": 3645.0,
                            "description": "přijaté pojistné plnění (RZ 53/2026/RM)",
                        },
                        {
                            "budget_change_id": "53/2026/RM",
                            "raw_codes": ["6320", "5362"],
                            "amount": "-3 645,00",
                            "amount_value": -3645.0,
                            "description": "převod mezi položkami (RZ 53/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 53/2026/RM",
                    "text": "Důvod rozpočtové změny.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            permalink = write_ro_page(opatreni, output)
            page = output / "rozpoctova-opatreni" / "RO-6-2026" / "index.html"
            text = page.read_text(encoding="utf-8")

        self.assertEqual(permalink, "/rozpoctova-opatreni/RO-6-2026/")
        self.assertIn('<p class="usn-back">', text)
        self.assertIn('<a href="/rozpoctova-opatreni/" id="back-link">← Zpět na rozpočtová opatření</a>', text)
        self.assertIn('<script src="/usneseni/back-link.js" defer data-back-prefixes="/usneseni /rozpoctova-opatreni"></script>', text)
        self.assertNotIn("<script>", text)
        self.assertIn('id="rz-53-2026-rm"', text)
        self.assertIn('/usneseni/2026/RM-2161-69-2026/', text)
        self.assertIn('organ: "Rada města Litovel"', text)
        self.assertIn("rozpoctove_opatreni: true", text)
        self.assertIn('<header class="usn-ro-hero">', text)
        self.assertIn('<p class="usn-ro-kicker">Rozpočet města</p>', text)
        self.assertIn('<p class="usn-ro-lead">Obsahuje 1 rozpočtová změna. Schváleno 12. 3. 2026.</p>', text)
        self.assertIn('<span>Rada města Litovel</span>', text)
        self.assertIn('<span>69. schůze</span>', text)
        self.assertNotIn('<span>12. 3. 2026</span>', text)
        self.assertEqual(text.count('id="rz-53-2026-rm"'), 1)
        self.assertEqual(text.count('Rozpočtová změna 53/2026/RM'), 1)
        self.assertIn('class="usn-rz-note"', text)
        self.assertIn('<p class="usn-rz-title">přijaté pojistné plnění</p>', text)
        self.assertIn('<p>Důvod rozpočtové změny.</p>', text)
        self.assertIn('<details class="usn-rz-details">', text)
        self.assertIn('<summary>Účetní řádky a kódy (2)</summary>', text)
        self.assertNotIn('Do rozpočtu přišlo</span>', text)
        self.assertNotIn('Přesun v rámci příjmů bez změny celku', text)
        self.assertIn('přijaté pojistné plnění</p>', text)
        self.assertNotIn('přijaté pojistné plnění (RZ 53/2026/RM)</p>', text)
        self.assertIn('<summary>Kódy: POL 6320, ORG 2322</summary>', text)

    def test_write_ro_page_uses_row_description_when_note_missing(self):
        opatreni = {
            "id": "RO/1/2026",
            "approval_date": "2026-01-29",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 67, "type": "schůzi", "date": "2026-01-29"},
            "budget_change_ids": ["42/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "42/2026/RM",
                            "raw_codes": ["3392", "5137"],
                            "amount": "120 000,00",
                            "amount_value": 120000.0,
                            "description": "Unčovice - židle a stoly pro KD (RZ 42/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-1-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn('<p class="usn-rz-title">Unčovice - židle a stoly pro KD</p>', text)
        self.assertIn('<summary>Účetní řádky a kódy (1)</summary>', text)
        self.assertNotIn('Ve výdajích přibylo</span>', text)

    def test_write_ro_page_prefers_specific_row_title_over_reserve_line(self):
        opatreni = {
            "id": "RO/7/2026",
            "approval_date": "2026-04-02",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 70, "type": "schůzi", "date": "2026-04-02"},
            "budget_change_ids": ["79/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "79/2026/RM",
                            "raw_codes": ["3639", "5901", "310", "2 030 000"],
                            "amount": "-89 843,00",
                            "amount_value": -89843.0,
                            "description": "Unčovice - rezerva (RZ 79/2026/RM)",
                        },
                        {
                            "budget_change_id": "79/2026/RM",
                            "raw_codes": ["3392", "5171", "310", "2 033 465"],
                            "amount": "89 843,00",
                            "amount_value": 89843.0,
                            "description": "Unčovice - Sokolovna - renovace vnitřních prostor (RZ 79/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 79/2026/RM",
                    "text": "Dne 25.3.2026 požádal odbor MH a SI o rozpočtovou změnu.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-7-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn('<p class="usn-rz-title">Unčovice - Sokolovna - renovace vnitřních prostor</p>', text)
        self.assertNotIn('<p class="usn-rz-title">Unčovice - rezerva</p>', text)

    def test_write_ro_page_prefers_note_title_for_mixed_row_bundle(self):
        opatreni = {
            "id": "RO/5/2026",
            "approval_date": "2026-03-05",
            "approved_by": "Zastupitelstvem města Litovel",
            "meeting": {"number": 25, "type": "zasedání", "date": "2026-03-05"},
            "budget_change_ids": ["42/2026/ZM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "prijmy",
                    "rows": [
                        {
                            "budget_change_id": "42/2026/ZM",
                            "raw_codes": ["231", "3111", "2229", "48"],
                            "amount": "101 706,00",
                            "amount_value": 101706.0,
                            "description": "MŠ Gemerská - ostatní přijaté vratky transferů a podobné příjmy (RZ 42/2026/ZM)",
                        },
                        {
                            "budget_change_id": "42/2026/ZM",
                            "raw_codes": ["231", "3113", "2229", "46"],
                            "amount": "45 019,82",
                            "amount_value": 45019.82,
                            "description": "ZŠ Jungmannova - ostatní přijaté vratky transferů a podobné příjmy (RZ 42/2026/ZM)",
                        },
                        {
                            "budget_change_id": "42/2026/ZM",
                            "raw_codes": ["231", "6320", "2322", "0"],
                            "amount": "262 537,00",
                            "amount_value": 262537.0,
                            "description": "přijaté pojistné plnění - povodeň 2024 (RZ 42/2026/ZM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 42/2026/ZM",
                    "text": (
                        "V průběhu ledna a února obdrželo město Litovel na svůj účet od příspěvkových organizací "
                        "vratky nevyčerpaných provozních příspěvků na spotřebu energií za rok 2025, také pojistné "
                        "plnění a neinvestiční přijaté transfery od obcí."
                    ),
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-5-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn(
            "<p class=\"usn-rz-title\">Od příspěvkových organizací vratky nevyčerpaných provozních příspěvků na spotřebu energií za rok 2025, také pojistné plnění a neinvestiční přijaté transfery od obcí</p>",
            text,
        )
        self.assertNotIn('<p class="usn-rz-title">MŠ Gemerská - ostatní přijaté vratky transferů a podobné příjmy</p>', text)
        self.assertNotIn('Do rozpočtu přišlo</span>', text)

    def test_write_ro_page_renders_full_note_text(self):
        opatreni = {
            "id": "RO/22/2025",
            "approval_date": "2025-11-27",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 63, "type": "schůzi", "date": "2025-11-27"},
            "budget_change_ids": ["167/2025/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "167/2025/RM",
                            "raw_codes": ["2219", "6121"],
                            "amount": "-106 280,00",
                            "amount_value": -106280.0,
                            "description": "Unčovice - revitalizace veřejných ploch u Sokolovny (RZ 167/2025/RM)",
                        },
                        {
                            "budget_change_id": "167/2025/RM",
                            "raw_codes": ["3392", "5169"],
                            "amount": "106 280,00",
                            "amount_value": 106280.0,
                            "description": "Unčovice - Sokolovna - renovace místnosti (RZ 167/2025/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 167/2025/RM",
                    "text": (
                        "Dne 19. 11. 2025 požádal odbor MH a SI o rozpočtovou změnu. "
                        "V Sokolovně v místní části Unčovice se nachází místnost v neuživatelném stavu."
                    ),
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-22-2025" / "index.html").read_text(encoding="utf-8")

        self.assertIn(
            "<p>Dne 19. 11. 2025 požádal odbor MH a SI o rozpočtovou změnu. V Sokolovně v místní části Unčovice se nachází místnost v neuživatelném stavu.</p>",
            text,
        )
        self.assertNotIn("<p>Dne 19.</p>", text)

    def test_write_ro_page_shows_reallocation_as_increase_and_decrease(self):
        opatreni = {
            "id": "RO/2/2026",
            "approval_date": "2026-02-12",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 68, "type": "schůzi", "date": "2026-02-12"},
            "budget_change_ids": ["12/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "12/2026/RM",
                            "raw_codes": ["3392", "5169"],
                            "amount": "300 000,00",
                            "amount_value": 300000.0,
                            "description": "Kulturní dům - služby (RZ 12/2026/RM)",
                        },
                        {
                            "budget_change_id": "12/2026/RM",
                            "raw_codes": ["3392", "5171"],
                            "amount": "-300 000,00",
                            "amount_value": -300000.0,
                            "description": "Kulturní dům - opravy (RZ 12/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 12/2026/RM",
                    "text": "Přesun mezi výdajovými položkami kulturního domu.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-2-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn('<p class="usn-rz-explanation">Rozpočtově: přesun 300 000,00 Kč z položky Kulturní dům - opravy na služby pro Kulturní dům.</p>', text)
        self.assertNotIn('Ve výdajích přibylo</span> <strong class="usn-amount usn-amount-positive">+300 000,00 Kč</strong>', text)
        self.assertNotIn('Ve výdajích ubylo</span> <strong class="usn-amount usn-amount-negative">300 000,00 Kč</strong>', text)
        self.assertNotIn('Přesun v rámci výdajů bez změny celku', text)

    def test_write_ro_page_describes_reallocation_target_from_positive_row(self):
        opatreni = {
            "id": "RO/8/2026",
            "approval_date": "2026-04-02",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 70, "type": "schůzi", "date": "2026-04-02"},
            "budget_change_ids": ["82/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "82/2026/RM",
                            "raw_codes": ["4359", "5222"],
                            "amount": "5 000,00",
                            "amount_value": 5000.0,
                            "description": "Zet-My, z.s. - dar na podporu činnosti odlehčovací služby (RZ 82/2026/RM)",
                        },
                        {
                            "budget_change_id": "82/2026/RM",
                            "raw_codes": ["6409", "5901"],
                            "amount": "-5 000,00",
                            "amount_value": -5000.0,
                            "description": "transfery dle rozhodnutí ZML a RML (RZ 82/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 82/2026/RM",
                    "text": "Dar na základě žádosti.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-8-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn(
            '<p class="usn-rz-explanation">Rozpočtově: přesun 5 000,00 Kč na dar na podporu činnosti odlehčovací služby pro Zet-My, z.s.</p>',
            text,
        )
        self.assertNotIn('V rámci rozpočtu se přesouvá 5 000,00 Kč na jiný účel.', text)
        self.assertNotIn('Ve výdajích přibylo</span> <strong class="usn-amount usn-amount-positive">+5 000,00 Kč</strong>', text)

    def test_write_ro_page_explains_reallocation_source_and_target(self):
        opatreni = {
            "id": "RO/7/2026",
            "approval_date": "2026-04-02",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 70, "type": "schůzi", "date": "2026-04-02"},
            "budget_change_ids": ["77/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "77/2026/RM",
                            "raw_codes": ["3639", "5172", "7 000 000"],
                            "amount": "-50 000,00",
                            "amount_value": -50000.0,
                            "description": "OŽP - zpracování PD k vynětí půdy (RZ 77/2026/RM)",
                        },
                        {
                            "budget_change_id": "77/2026/RM",
                            "raw_codes": ["3722", "5169", "7 000 000"],
                            "amount": "50 000,00",
                            "amount_value": 50000.0,
                            "description": "svoz komunálního odpadu (RZ 77/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 77/2026/RM",
                    "text": "Dne 24.3.2026 požádal vedoucí OŽP o rozpočtovou změnu.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-7-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn('<p class="usn-rz-title">svoz komunálního odpadu</p>', text)
        self.assertIn(
            '<p class="usn-rz-explanation">Rozpočtově: přesun 50 000,00 Kč z položky OŽP - zpracování PD k vynětí půdy na svoz komunálního odpadu.</p>',
            text,
        )
        self.assertNotIn('<p class="usn-rz-title">OŽP - zpracování PD k vynětí půdy</p>', text)

    def test_write_ro_page_explanation_strips_city_footer_from_transfer_target(self):
        opatreni = {
            "id": "RO/7/2026",
            "approval_date": "2026-04-02",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 70, "type": "schůzi", "date": "2026-04-02"},
            "budget_change_ids": ["76/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "76/2026/RM",
                            "raw_codes": ["5213", "5901"],
                            "amount": "-96 800,00",
                            "amount_value": -96800.0,
                            "description": "KŘ - rezervy dle krizového zákona (RZ 76/2026/RM)",
                        },
                        {
                            "budget_change_id": "76/2026/RM",
                            "raw_codes": ["3744", "5169"],
                            "amount": "96 800,00",
                            "amount_value": 96800.0,
                            "description": "Město Litovel ID datové schránky: 4rub4s3 e-mail: sekretariat@mestolitovel.cz IČO 229138 Tel.: +420 585 153 111 www.litovel.eu č. účtu: 3620811/0100 KŘ - převod a aktualizace digitálního povodňového plánu - město Litovel a ORP Litovel (RZ 76/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 76/2026/RM",
                    "text": "Rozpočtová změna na základě požadavku pracovníka krizového řízení.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-7-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn(
            '<p class="usn-rz-explanation">Rozpočtově: přesun 96 800,00 Kč z položky KŘ - rezervy dle krizového zákona na převod a aktualizace digitálního povodňového plánu - město Litovel a ORP Litovel pro KŘ.</p>',
            text,
        )
        self.assertNotIn(
            'Rozpočtově: přesun 96 800,00 Kč z položky KŘ - rezervy dle krizového zákona na převod a aktualizace digitálního povodňového plánu - město Litovel a ORP Litovel pro Město Litovel',
            text,
        )

    def test_write_ro_page_explains_same_label_transfer_as_reclassification(self):
        opatreni = {
            "id": "RO/7/2026",
            "approval_date": "2026-04-02",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 70, "type": "schůzi", "date": "2026-04-02"},
            "budget_change_ids": ["72/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "72/2026/RM",
                            "raw_codes": ["3429", "5499", "4 000 000"],
                            "amount": "-5 000,00",
                            "amount_value": -5000.0,
                            "description": 'R.Š. - dar na organizační zajištění kulturní akce s názvem "1. máj v Parku Míru 2026" (RZ 72/2026/RM)',
                        },
                        {
                            "budget_change_id": "72/2026/RM",
                            "raw_codes": ["3429", "5492", "4 000 000"],
                            "amount": "5 000,00",
                            "amount_value": 5000.0,
                            "description": 'R.Š. - dar na organizační zajištění kulturní akce s názvem "1. máj v Parku Míru 2026" (RZ 72/2026/RM)',
                        },
                        {
                            "budget_change_id": "72/2026/RM",
                            "raw_codes": ["3429", "5499", "4 000 000"],
                            "amount": "-2 500,00",
                            "amount_value": -2500.0,
                            "description": "K.H. - dar na organizační zajištění hudebních odpolední (RZ 72/2026/RM)",
                        },
                        {
                            "budget_change_id": "72/2026/RM",
                            "raw_codes": ["3429", "5492", "4 000 000"],
                            "amount": "2 500,00",
                            "amount_value": 2500.0,
                            "description": "K.H. - dar na organizační zajištění hudebních odpolední (RZ 72/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 72/2026/RM",
                    "text": "Dva příspěvky pro FO byly rozhodnutím RM schváleny ne jako dotace, ale jako dary.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-7-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn(
            '<p class="usn-rz-explanation">Rozpočtově: mění se rozpočtové zařazení výdajů v celkové výši 7 500,00 Kč. Celková výše výdajů se nemění.</p>',
            text,
        )
        self.assertNotIn("V rozpočtu se přesouvá 7 500,00 Kč", text)

    def test_write_ro_page_explains_income_balanced_by_financing(self):
        opatreni = {
            "id": "RO/7/2026",
            "approval_date": "2026-04-02",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 70, "type": "schůzi", "date": "2026-04-02"},
            "budget_change_ids": ["74/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "prijmy",
                    "rows": [
                        {
                            "budget_change_id": "74/2026/RM",
                            "raw_codes": ["4121"],
                            "amount": "39 900,00",
                            "amount_value": 39900.0,
                            "description": "neinvestiční přijaté transfery od obcí (RZ 74/2026/RM)",
                        },
                    ],
                },
                {
                    "type": "financovani",
                    "rows": [
                        {
                            "budget_change_id": "74/2026/RM",
                            "raw_codes": ["8115"],
                            "amount": "-39 900,00",
                            "amount_value": -39900.0,
                            "description": "změna stavu krátkodobých prostředků (RZ 74/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 74/2026/RM",
                    "text": "V měsících lednu a únoru přijalo město Litovel neinv. transfery od obcí.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-7-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn(
            '<p class="usn-rz-explanation">Rozpočtově: město přijalo 39 900,00 Kč. Tato změna nezvyšuje výdaje; promítá se do peněz na účtech města.</p>',
            text,
        )
        self.assertNotIn('Do rozpočtu přišlo</span> <strong class="usn-amount usn-amount-positive">+39 900,00 Kč</strong>', text)
        self.assertNotIn('Snížení financování</span> <strong class="usn-amount usn-amount-negative">39 900,00 Kč</strong>', text)

    def test_write_ro_page_explains_expense_funded_from_account_balance(self):
        opatreni = {
            "id": "RO/3/2026",
            "approval_date": "2026-02-12",
            "approved_by": "Zastupitelstvem města Litovel",
            "meeting": {"number": 24, "type": "zasedání", "date": "2026-02-12"},
            "budget_change_ids": ["5/2026/ZM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "financovani",
                    "rows": [
                        {
                            "budget_change_id": "5/2026/ZM",
                            "raw_codes": ["8115"],
                            "amount": "300 000,00",
                            "amount_value": 300000.0,
                            "description": "změna stavu krátkodobých prostředků na bankovních účtech .. (RZ 5/2026/ZM)",
                        },
                    ],
                },
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "5/2026/ZM",
                            "raw_codes": ["3613", "5189", "3 000 000"],
                            "amount": "300 000,00",
                            "amount_value": 300000.0,
                            "description": "jistina dle dražební vyhlášky - dům na ul. 1. máje (RZ 5/2026/ZM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 5/2026/ZM",
                    "text": "Jistina dle dražební vyhlášky.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-3-2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn('<p class="usn-rz-title">jistina dle dražební vyhlášky - dům na ul. 1. máje</p>', text)
        self.assertIn(
            '<p class="usn-rz-explanation">Rozpočtově: do výdajů se zapojuje 300 000,00 Kč z peněz na účtech města. Účel: jistina dle dražební vyhlášky - dům na ul. 1. máje.</p>',
            text,
        )
        self.assertNotIn('<p class="usn-rz-title">změna stavu krátkodobých prostředků', text)

    def test_write_ro_page_merges_same_rz_across_sections_and_keeps_amounts_visible(self):
        opatreni = {
            "id": "RO/9/2026",
            "approval_date": "2026-04-16",
            "approved_by": "Radou města Litovel",
            "meeting": {"number": 72, "type": "schůzi", "date": "2026-04-16"},
            "budget_change_ids": ["91/2026/RM"],
            "resolution_links": [],
            "sections": [
                {
                    "type": "prijmy",
                    "rows": [
                        {
                            "budget_change_id": "91/2026/RM",
                            "raw_codes": ["4116", "12345"],
                            "amount": "200 000,00",
                            "amount_value": 200000.0,
                            "description": "dotace na opravu sokolovny (RZ 91/2026/RM)",
                        },
                    ],
                },
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "91/2026/RM",
                            "raw_codes": ["3392", "5171"],
                            "amount": "150 000,00",
                            "amount_value": 150000.0,
                            "description": "Sokolovna - opravy (RZ 91/2026/RM)",
                        },
                        {
                            "budget_change_id": "91/2026/RM",
                            "raw_codes": ["3392", "6121"],
                            "amount": "50 000,00",
                            "amount_value": 50000.0,
                            "description": "Sokolovna - technické zhodnocení (RZ 91/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 91/2026/RM",
                    "text": "Město přijalo dotaci a použije ji na opravu a technické zhodnocení sokolovny.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_page(opatreni, output)
            text = (output / "rozpoctova-opatreni" / "RO-9-2026" / "index.html").read_text(encoding="utf-8")

        self.assertEqual(text.count('Rozpočtová změna 91/2026/RM'), 1)
        self.assertIn('id="rz-91-2026-rm"', text)
        self.assertIn('<p class="usn-rz-explanation">Rozpočtově: město přijalo 200 000,00 Kč a stejnou částku zařadilo do výdajů.</p>', text)
        self.assertNotIn('Do rozpočtu přišlo</span>', text)
        self.assertNotIn('Ve výdajích přibylo</span>', text)
        self.assertIn('<strong class="usn-amount usn-amount-positive">200 000,00</strong>', text)
        self.assertIn('<strong class="usn-amount usn-amount-positive">150 000,00</strong>', text)
        self.assertIn('<strong class="usn-amount usn-amount-positive">50 000,00</strong>', text)
        self.assertIn('<p class="usn-rz-row-section">Příjmy</p>', text)
        self.assertIn('<p class="usn-rz-row-section">Výdaje</p>', text)
        self.assertLess(text.index('<h2>Rozpočtové změny</h2>'), text.index('<summary>Co znamenají kódy rozpočtové skladby</summary>'))

    def test_financing_section_is_inferred_from_8xxx_codes(self):
        sections = normalize_financing_sections([
            {
                "type": "vydaje",
                "label": "Změny ve výdajích",
                "rows": [
                    {
                        "budget_change_id": "74/2026/RM",
                        "raw_codes": ["8115"],
                    }
                ],
            }
        ])

        self.assertEqual(sections[0]["type"], "financovani")
        self.assertEqual(sections[0]["label"], "Změny ve financování")

    def test_opatreni_are_grouped_by_content_year(self):
        grouped = group_opatreni_by_content_year([
            {"id": "RO/25/2025", "year": 2025, "approval_date": "2026-01-29"},
            {"id": "RO/1/2026", "year": 2026, "approval_date": "2025-12-11"},
        ])

        self.assertEqual([item["id"] for item in grouped["2025"]], ["RO/25/2025"])
        self.assertEqual([item["id"] for item in grouped["2026"]], ["RO/1/2026"])

    def test_year_index_contains_ro_after_meetings(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_year_index(
                "2026",
                [("RM/1/1/2026", "/usneseni/2026/RM-1-1-2026/", "2026-01-10")],
                [("RM-1", "/usneseni/2026/RM-1/", "2026-01-10")],
                output,
                [
                    {
                        "id": "RO/25/2025",
                        "number": 25,
                        "year": 2025,
                        "approval_date": "2026-01-29",
                        "organ": "RM",
                        "budget_change_ids": ["1/2026/RM", "2/2026/RM"],
                        "sections": [
                            {
                                "type": "vydaje",
                                "rows": [
                                    {
                                        "budget_change_id": "1/2026/RM",
                                        "raw_codes": ["3113", "5169"],
                                        "amount": "100 000,00",
                                        "amount_value": 100000.0,
                                        "description": "ZŠ Jungmannova - služby (RZ 1/2026/RM)",
                                    },
                                    {
                                        "budget_change_id": "2/2026/RM",
                                        "raw_codes": ["2321", "6121"],
                                        "amount": "250 000,00",
                                        "amount_value": 250000.0,
                                        "description": "ČOV Litovel - technické úpravy (RZ 2/2026/RM)",
                                    },
                                ],
                            },
                        ],
                        "notes": [
                            {
                                "title": "Rozpočtová změna č. 1/2026/RM",
                                "text": "Dotace pro školu a související výdaje.",
                            }
                        ],
                    },
                ],
            )
            text = (output / "usneseni" / "2026" / "index.html").read_text(encoding="utf-8")

        self.assertIn('<div class="usn-year-ro-list">', text)
        self.assertIn('<div class="usn-year-ro-card"><a href="/rozpoctova-opatreni/RO-25-2025/">RO-25-2025 <span class="usn-date">29. 1.</span></a>', text)
        self.assertIn('<div class="usn-summary">2 změn: školy, ČOV / voda, dary a dotace</div>', text)
        self.assertIn('<a href="/rozpoctova-opatreni/">Všechna rozpočtová opatření</a>', text)
        self.assertLess(text.index("<h2>Schůze</h2>"), text.index("<h2>Rozpočtová opatření</h2>"))

    def test_year_index_orders_meeting_groups_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_year_index(
                "2026",
                [
                    ("RM/20/2/2026", "/usneseni/2026/RM-20-2-2026/", "2026-02-10"),
                    ("RM/3/10/2026", "/usneseni/2026/RM-3-10-2026/", "2026-05-01"),
                    ("ZM/1/9/2026", "/usneseni/2026/ZM-1-9-2026/", "2026-04-20"),
                ],
                [("RM-10", "/usneseni/2026/RM-10/", "2026-05-01")],
                output,
                [],
            )
            text = (output / "usneseni" / "2026" / "index.html").read_text(encoding="utf-8")

        grouped_start = text.index("<h2>Schůze</h2>")
        grouped_block = text[grouped_start:]

        self.assertIn("Rada města · schůze 10", grouped_block)
        self.assertIn("Zastupitelstvo · schůze 9", grouped_block)
        self.assertLess(grouped_block.index("Rada města · schůze 10"), grouped_block.index("Zastupitelstvo · schůze 9"))
        self.assertLess(grouped_block.index("Zastupitelstvo · schůze 9"), grouped_block.index("Rada města · schůze 2"))

    def test_ro_index_contains_people_facing_summary(self):
        opatreni = {
            "id": "RO/7/2026",
            "number": 7,
            "year": 2026,
            "approval_date": "2026-04-02",
            "approved_by": "Radou města Litovel",
            "budget_change_ids": ["79/2026/RM", "80/2026/RM"],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "79/2026/RM",
                            "raw_codes": ["3392", "5171"],
                            "amount": "89 843,00",
                            "amount_value": 89843.0,
                            "description": "Unčovice - Sokolovna - renovace vnitřních prostor (RZ 79/2026/RM)",
                        },
                        {
                            "budget_change_id": "80/2026/RM",
                            "raw_codes": ["3113", "5336"],
                            "amount": "576 810,80",
                            "amount_value": 576810.8,
                            "description": "ZŠ a MŠ Nasobůrky - dotace OP JAK (RZ 80/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [
                {
                    "title": "Rozpočtová změna č. 80/2026/RM",
                    "text": "Město přijalo účelovou dotaci určenou pro školu.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_ro_index([opatreni], output)
            text = (output / "rozpoctova-opatreni" / "index.html").read_text(encoding="utf-8")

        self.assertIn('<div class="usn-snippet">2 změn: místní části, školy, dary a dotace, kultura a sport</div>', text)
        self.assertIn('<div class="usn-summary">Týká se: Unčovice / Sokolovna, ZŠ a MŠ Nasobůrky</div>', text)

    def test_ro_summary_uses_top_categories_across_rz_not_full_union(self):
        opatreni = {
            "id": "RO/8/2026",
            "number": 8,
            "year": 2026,
            "approval_date": "2026-05-01",
            "approved_by": "Radou města Litovel",
            "budget_change_ids": [
                "1/2026/RM",
                "2/2026/RM",
                "3/2026/RM",
                "4/2026/RM",
                "5/2026/RM",
                "6/2026/RM",
            ],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "1/2026/RM",
                            "raw_codes": ["3113", "5336"],
                            "amount": "100 000,00",
                            "amount_value": 100000.0,
                            "description": "ZŠ Jungmannova - dotace na vybavení (RZ 1/2026/RM)",
                        },
                        {
                            "budget_change_id": "2/2026/RM",
                            "raw_codes": ["3111", "5336"],
                            "amount": "90 000,00",
                            "amount_value": 90000.0,
                            "description": "MŠ Gemerská - dotace na provoz (RZ 2/2026/RM)",
                        },
                        {
                            "budget_change_id": "3/2026/RM",
                            "raw_codes": ["2321", "6121"],
                            "amount": "250 000,00",
                            "amount_value": 250000.0,
                            "description": "ČOV Litovel - technické úpravy (RZ 3/2026/RM)",
                        },
                        {
                            "budget_change_id": "4/2026/RM",
                            "raw_codes": ["3392", "5171"],
                            "amount": "80 000,00",
                            "amount_value": 80000.0,
                            "description": "Unčovice - Sokolovna - renovace sálu (RZ 4/2026/RM)",
                        },
                        {
                            "budget_change_id": "5/2026/RM",
                            "raw_codes": ["2219", "5171"],
                            "amount": "70 000,00",
                            "amount_value": 70000.0,
                            "description": "Místní komunikace - oprava chodníku (RZ 5/2026/RM)",
                        },
                        {
                            "budget_change_id": "6/2026/RM",
                            "raw_codes": ["5512", "5137"],
                            "amount": "60 000,00",
                            "amount_value": 60000.0,
                            "description": "JSDH - vybavení po povodni (RZ 6/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [],
        }

        self.assertEqual(
            aggregate_top_categories(opatreni),
            ["školy", "dary a dotace", "doprava", "ČOV / voda"],
        )
        self.assertEqual(
            summarize_opatreni_plain(opatreni),
            "6 změn: školy, dary a dotace, doprava, ČOV / voda",
        )

    def test_extracts_affected_place_service_from_title(self):
        self.assertEqual(
            affected_place_service_from_title("Unčovice - Sokolovna - renovace vnitřních prostor"),
            "Unčovice / Sokolovna",
        )
        self.assertEqual(
            affected_place_service_from_title("ZŠ a MŠ Nasobůrky - dotace OP JAK"),
            "ZŠ a MŠ Nasobůrky",
        )
        self.assertEqual(
            affected_place_service_from_title("přijaté pojistné plnění"),
            "",
        )
        self.assertEqual(
            affected_place_service_from_title("NSA - účelová inv. dotace - Revitalizace sportovního areálu Sokolovny v Litovli - 2. etapa"),
            "Revitalizace sportovního areálu Sokolovny v Litovli",
        )
        self.assertEqual(
            affected_place_service_from_title("volby do Poslanecké sněmovny Parlamentu ČR - dotace"),
            "volby do Poslanecké sněmovny Parlamentu ČR",
        )
        self.assertEqual(
            affected_place_service_from_title("J.P. - dotace na činnost družstva malé kopané"),
            "malé kopané",
        )

    def test_summarize_affected_places_keeps_stable_order(self):
        opatreni = {
            "id": "RO/9/2026",
            "budget_change_ids": ["79/2026/RM", "80/2026/RM", "81/2026/RM"],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "79/2026/RM",
                            "description": "Unčovice - Sokolovna - renovace sálu (RZ 79/2026/RM)",
                        },
                        {
                            "budget_change_id": "80/2026/RM",
                            "description": "ZŠ a MŠ Nasobůrky - dotace OP JAK (RZ 80/2026/RM)",
                        },
                        {
                            "budget_change_id": "81/2026/RM",
                            "description": "ČOV Litovel - technické úpravy (RZ 81/2026/RM)",
                        },
                    ],
                },
            ],
            "notes": [],
        }

        self.assertEqual(
            summarize_affected_places(opatreni),
            "Unčovice / Sokolovna, ZŠ a MŠ Nasobůrky, ČOV Litovel",
        )

    def test_ro_14_2025_uses_broad_relatable_mentions(self):
        opatreni = {
            "id": "RO/14/2025",
            "budget_change_ids": ["114/2025/RM", "117/2025/RM", "118/2025/RM", "126/2025/RM"],
            "sections": [
                {
                    "type": "vydaje",
                    "rows": [
                        {
                            "budget_change_id": "114/2025/RM",
                            "description": "volby do Poslanecké sněmovny Parlamentu ČR - dotace (RZ 114/2025/RM)",
                        },
                        {
                            "budget_change_id": "117/2025/RM",
                            "description": "Revitalizace sportovního areálu Sokolovny v Litovli - 2. etapa - dotace (RZ 117/2025/RM)",
                        },
                        {
                            "budget_change_id": "118/2025/RM",
                            "description": "J.P. - dotace na činnost družstva malé kopané (RZ 118/2025/RM)",
                        },
                        {
                            "budget_change_id": "126/2025/RM",
                            "description": "T.R. - dotace na činnost družstva malé kopané + oslava 30. výročí založení mk v Unčovicích (RZ 126/2025/RM)",
                        },
                    ],
                },
            ],
            "notes": [],
        }

        self.assertEqual(
            summarize_affected_places(opatreni),
            "volby do Poslanecké sněmovny Parlamentu ČR, Revitalizace sportovního areálu Sokolovny v Litovli, malé kopané, …",
        )


if __name__ == "__main__":
    unittest.main()
