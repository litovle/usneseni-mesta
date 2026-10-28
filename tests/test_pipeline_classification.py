import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import phase2_resolution_analysis
from pipeline import build_stages
from phase3_resolve_references import process_resolutions


class PipelineClassificationTest(unittest.TestCase):
    def test_pipeline_enables_final_classifier_in_enrich_stage(self):
        stages = build_stages(Path("pdf"), Path("ro"), Path("work"), Path("export"),
                              classifier_url="https://example.com/model.tar.gz", classifier_sha256="a" * 64)
        command = next(stage for stage in stages if stage["name"] == "enrich")["operations"][0]["command"]
        self.assertEqual(command[command.index("--classifier-url") + 1], "https://example.com/model.tar.gz")
        self.assertEqual(command[command.index("--classifier-sha256") + 1], "a" * 64)
        self.assertEqual(command[command.index("--classification-output") + 1], "work/classifier")
        self.assertEqual([stage["name"] for stage in stages], ["extract", "enrich", "export"])

    def test_pipeline_can_enable_incremental_classification(self):
        stages = build_stages(Path("pdf"), Path("ro"), Path("work"), Path("export"),
                              incremental_classification=True)
        command = stages[1]["operations"][0]["command"]
        self.assertIn("--incremental-classification", command)
        workflows = [Path(".github/workflows/sync-litovel-notices.yml"),
                     Path(".github/workflows/manual-litovel-pdf.yml")]
        for workflow in workflows:
            self.assertIn('"--incremental-classification"', workflow.read_text())

    def test_classification_survives_analysis_and_reference_resolution(self):
        classification = {"category": "culture", "source": "model", "status": "classified",
                          "prediction": {"category": "culture", "confidence": 0.54}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "phase1"
            source.mkdir()
            (source / "resolution.json").write_text(json.dumps({
                "id": "RM/1/1/2022", "datum": "2022-10-27",
                "text_raw": "Rada města Litovel schvaluje kulturní akci.",
            }), encoding="utf-8")
            argv = ["phase2_resolution_analysis.py", "--input", str(source), "--output", str(root / "phase3"),
                    "--classifier-url", "https://example.com/model.tar.gz"]
            with patch.object(sys, "argv", argv), patch("resolution_classification.runner.classify_records",
                                                       return_value={"RM/1/1/2022": classification}):
                phase2_resolution_analysis.main()
            parsed = json.loads((root / "phase3/resolution.json").read_text())
            self.assertEqual(parsed["classification"], classification)
            resolved, _, _ = process_resolutions([parsed])
            self.assertEqual(resolved[0]["classification"], classification)

    def test_incremental_analysis_reuses_previous_output(self):
        from resolution_classification.runner import text_hash
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "phase1"
            output = root / "phase3"
            source.mkdir()
            output.mkdir()
            raw = {"id": "RM/1/1/2022", "datum": "2022-10-27",
                   "text_raw": "Rada města Litovel schvaluje kulturní akci."}
            classification = {"category": "culture", "source": "model", "status": "classified",
                              "model_url": "model", "model_sha256": "checksum",
                              "text_sha256": text_hash(raw["text_raw"]),
                              "prediction": {"category": "culture", "confidence": 0.8,
                                             "second_category": "sport", "second_confidence": 0.1,
                                             "margin": 0.7, "entropy": 0.2}}
            (source / "resolution.json").write_text(json.dumps(raw), encoding="utf-8")
            (output / "resolution.json").write_text(json.dumps({"id": raw["id"],
                                                                  "classification": classification}), encoding="utf-8")
            argv = ["phase2_resolution_analysis.py", "--input", str(source), "--output", str(output),
                    "--classifier-url", "model", "--classifier-sha256", "checksum",
                    "--incremental-classification"]
            with patch.object(sys, "argv", argv), \
                 patch("resolution_classification.runner.load_bundle") as load:
                phase2_resolution_analysis.main()
                load.assert_not_called()
            parsed = json.loads((output / "resolution.json").read_text())
            self.assertEqual(parsed["classification"], classification)


if __name__ == "__main__":
    unittest.main()
