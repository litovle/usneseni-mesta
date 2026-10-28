import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resolution_classification.inference import select_phase1_rows, write_reports
from resolution_classification.runner import classify_records, text_hash
from tools.check_classification_updates import count_pending


class IncrementalClassificationTest(unittest.TestCase):
    def test_changed_text_is_selected_and_written_with_new_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            phase1 = root / "phase1"
            analyzed = root / "phase3"
            phase1.mkdir()
            analyzed.mkdir()
            records = {"RM/1/1/2026": {"id": "RM/1/1/2026", "text_raw": "unchanged"},
                       "RM/2/1/2026": {"id": "RM/2/1/2026", "text_raw": "changed"}}
            old = {"category": "sport", "source": "model", "status": "classified",
                   "model_url": "model", "model_sha256": "sha", "text_sha256": text_hash("unchanged"),
                   "prediction": {"category": "sport", "confidence": 0.8,
                                  "second_category": "culture", "second_confidence": 0.1,
                                  "margin": 0.7, "entropy": 0.2}}
            for index, record in enumerate(records.values()):
                name = f"{index}.json"
                (phase1 / name).write_text(json.dumps(record), encoding="utf-8")
                saved = {"id": record["id"], "classification": old}
                (analyzed / name).write_text(json.dumps(saved), encoding="utf-8")

            self.assertEqual(count_pending(phase1, analyzed, "model", "sha"), 1)

            def infer(model_path, source, report, selected_ids=None):
                rows = select_phase1_rows(source, selected_ids)
                self.assertEqual([row["id"] for row in rows], ["RM/2/1/2026"])
                results = [{"id": row["id"], "text": row["text"], "category": "culture",
                            "confidence": 0.9, "second_category": "sport", "second_confidence": 0.05,
                            "margin": 0.85, "entropy": 0.2} for row in rows]
                write_reports(results, model_path, source, report)
                return results

            with patch("resolution_classification.runner.load_bundle",
                       return_value=(root, {"id2label": {"0": "sport", "1": "culture"}})), \
                 patch("resolution_classification.inference.run_classification", side_effect=infer):
                result = classify_records(records, phase1, root / "reports", "model", "sha",
                                          previous={"RM/1/1/2026": old,
                                                    "RM/2/1/2026": old})
            self.assertEqual(result["RM/1/1/2026"], old)
            self.assertEqual(result["RM/2/1/2026"]["text_sha256"], text_hash("changed"))
            self.assertEqual(result["RM/2/1/2026"]["category"], "culture")
            (analyzed / "1.json").write_text(
                json.dumps({"id": "RM/2/1/2026", "classification": result["RM/2/1/2026"]}),
                encoding="utf-8",
            )
            self.assertEqual(count_pending(phase1, analyzed, "model", "sha"), 0)
            self.assertEqual(count_pending(phase1, analyzed, "new-model", "sha"), 2)
            self.assertEqual(count_pending(phase1, analyzed, "model", "new-sha"), 2)

    def test_scheduled_workflow_runs_for_model_changes_without_new_pdf(self):
        workflow = Path(".github/workflows/sync-litovel-notices.yml").read_text(encoding="utf-8")
        self.assertIn("python -m tools.check_classification_updates", workflow)
        self.assertIn("steps.classification.outputs.changed == 'true'", workflow)


if __name__ == "__main__":
    unittest.main()
