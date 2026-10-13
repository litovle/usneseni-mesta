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

    def test_classification_survives_analysis_and_reference_resolution(self):
        classification = {"category": "culture", "source": "manual_override", "status": "classified",
                          "prediction": {"category": "education", "confidence": 0.54}}
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


if __name__ == "__main__":
    unittest.main()
