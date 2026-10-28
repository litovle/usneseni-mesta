import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from generator.icons import ICON_FILES, icon_image
from generator.icon_selection import icon_for_record, icon_for_resolution
from generator.models import InputError, parse_data
from generator.render import render_file


ROOT = Path(__file__).resolve().parents[1]


class GeneratorTests(unittest.TestCase):
    def test_all_available_icons_render(self):
        for name in ICON_FILES:
            with self.subTest(icon=name):
                icon = icon_image(name, 43)
                self.assertEqual(icon.size, (43, 43))
                self.assertIsNotNone(icon.getbbox())

    def test_logo_has_space_after_last_glyph(self):
        with Image.open(ROOT / "assets" / "litovle_logo.png") as logo:
            right = logo.getchannel("A").getbbox()[2]
            self.assertLessEqual(right, logo.width - 5)

    def test_examples_are_square_and_repeatable(self):
        for filename in ("waste_change.yaml", "council_summary.yaml", "council_summary_three.json",
                         "council_summary_from_resolutions.yaml"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                source = ROOT / "examples" / filename
                first = Path(directory) / "first.png"
                second = Path(directory) / "second.png"
                resolutions_dir = Path(directory) / "data"
                resolutions_dir.mkdir()
                (resolutions_dir / "2026.json").write_text(json.dumps([
                    {"id": "RM/2554/81/2026", "classification": {"category": "environment"}},
                    {"id": "RM/2563/81/2026", "classification": {"category": "administration"}},
                    {"id": "RM/2555/81/2026", "classification": {"category": "infrastructure"}},
                    {"id": "RM/2568/81/2026", "classification": {"category": "transport"}},
                ]), encoding="utf-8")
                render_file(source, first, resolutions_dir)
                render_file(source, second, resolutions_dir)
                with Image.open(first) as image:
                    self.assertEqual(image.size, (1080, 1080))
                    self.assertEqual(image.format, "PNG")
                self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_long_item_fails_before_output(self):
        source = (ROOT / "examples" / "council_summary.yaml").read_text(encoding="utf-8")
        source = source.replace("Revitalizace Novosad", "Příliš dlouhý nadpis " * 20)
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.yaml"
            output_path = Path(directory) / "output.png"
            input_path.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(InputError, r"items\[0\]\.title"):
                render_file(input_path, output_path)
            self.assertFalse(output_path.exists())

    def test_invalid_icon_is_explained(self):
        data = parse_data({
            "type": "council_summary",
            "meeting": {"body": "Rada", "session_label": "1. schůze", "subtitle": "Shrnutí", "footer": "Odkazy v příspěvku"},
            "items": [{"icon": "unknown", "title": "Bod", "text": "Text"}] * 3,
        })
        from generator.layouts import council_summary
        with self.assertRaisesRegex(InputError, "Neznámá ikona"):
            council_summary(data)

    def test_resolution_category_sets_default_and_explicit_icon_wins(self):
        self.assertEqual(icon_for_record({"id": "RM/2/1/2026", "classification": {"category": "transport"}}), "road")
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "2026.json").write_text(json.dumps([
                {"id": "RM/1/1/2026", "classification": {"category": "infrastructure"}},
                {"id": "RM/2/1/2026", "classification": {"category": "transport"}},
            ]), encoding="utf-8")
            data = parse_data({
                "type": "council_summary",
                "meeting": {"body": "Rada", "session_label": "1. schůze", "subtitle": "Shrnutí", "footer": "Odkazy v příspěvku"},
                "items": [
                    {"resolution_id": "RM/1/1/2026", "title": "Sítě", "text": "Projekt"},
                    {"resolution_id": "RM/1/1/2026", "icon": "water", "title": "Voda", "text": "Kanalizace"},
                    {"resolution_id": "RM/2/1/2026", "title": "Silnice", "text": "Oprava"},
                ],
            }, data_dir)
            self.assertEqual([item.icon for item in data.items], ["construction", "water", "road"])

            bad_id = {
                "type": "council_summary",
                "meeting": {"body": "Rada", "session_label": "1. schůze", "subtitle": "Shrnutí", "footer": "Odkazy"},
                "items": [{"resolution_id": "RM/999/1/2026", "icon": "water", "title": "Bod", "text": "Text"}] * 3,
            }
            with self.assertRaisesRegex(InputError, "není v exportu"):
                parse_data(bad_id, data_dir)

    def test_low_score_needs_explicit_icon(self):
        record = {"id": "RM/3/1/2026", "classification": {
            "category": "culture", "prediction": {"confidence": 0.46},
        }}
        with self.assertRaisesRegex(InputError, "nízké skóre"):
            icon_for_record(record)
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "2026.json").write_text(json.dumps([record]), encoding="utf-8")
            raw = {
                "type": "council_summary",
                "meeting": {"body": "Rada", "session_label": "1. schůze", "subtitle": "Shrnutí", "footer": "Odkazy"},
                "items": [{"resolution_id": record["id"], "title": "Pétanque", "text": "Podpora klubu"}] * 3,
            }
            with self.assertRaisesRegex(InputError, "nízké skóre"):
                parse_data(raw, data_dir)
            for item in raw["items"]:
                item["icon"] = "sport"
            self.assertEqual(parse_data(raw, data_dir).items[0].icon, "sport")

    def test_reloads_changed_resolution_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026.json"
            path.write_text(json.dumps([{"id": "RM/1/1/2026", "classification": {"category": "transport"}}]))
            self.assertEqual(icon_for_resolution("RM/1/1/2026", Path(directory)), "road")
            path.write_text(json.dumps([{"id": "RM/1/1/2026", "classification": {"category": "culture"}}]))
            self.assertEqual(icon_for_resolution("RM/1/1/2026", Path(directory)), "culture")

    def test_single_line_fields_reject_newlines(self):
        with self.assertRaisesRegex(InputError, "title_lines\\[0\\].*jednom řádku"):
            parse_data({"type": "waste_change", "place": "Litovel", "title_lines": ["Svoz\npapíru", "zítra"], "body": "Text"})
        with self.assertRaisesRegex(InputError, "meeting.body.*jednom řádku"):
            parse_data({"type": "council_summary", "meeting": {
                "body": "Rada\nměsta", "session_label": "1. schůze", "subtitle": "Shrnutí", "footer": "Odkazy",
            }, "items": [{"icon": "road", "title": "Bod", "text": "Text"}] * 3})


if __name__ == "__main__":
    unittest.main()
