import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resolution_classification.bundle import MODEL_FILES, load_bundle


def make_bundle(path, symlink=False):
    with tarfile.open(path, "w:gz") as archive:
        files = [f"model/{name}" for name in MODEL_FILES]
        for name in files:
            body = json.dumps({"id2label": {"0": "sport"}}).encode() if name == "model/config.json" else b"{}"
            member = tarfile.TarInfo(name)
            if symlink and name == "model/config.json":
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                archive.addfile(member)
            else:
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))
        extra = tarfile.TarInfo("../../outside")
        extra.size = 2
        archive.addfile(extra, io.BytesIO(b"{}"))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ClassifierBundleTest(unittest.TestCase):
    def test_download_verified_bundle_and_reuse_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.tar.gz"
            checksum = make_bundle(archive)
            bundle, config = load_bundle(archive.as_uri(), root / "cache", checksum)
            self.assertEqual(config["id2label"], {"0": "sport"})
            self.assertTrue((bundle / "model/model.safetensors").is_file())
            self.assertFalse((bundle / "taxonomy").exists())
            archive.unlink()
            self.assertEqual(load_bundle(archive.as_uri(), root / "cache", checksum)[0], bundle)
            (bundle / "model/config.json").write_text("corrupt")
            with self.assertRaisesRegex(ValueError, "damaged"):
                load_bundle(archive.as_uri(), root / "cache", checksum)

    def test_wrong_checksum_stops_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.tar.gz"
            make_bundle(archive)
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_bundle(archive.as_uri(), root / "cache", "0" * 64)

    def test_weights_only_release_needs_no_training_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.tar.gz"
            checksum = make_bundle(archive)
            bundle, config = load_bundle(archive.as_uri(), root / "cache", checksum)
            self.assertEqual(config["id2label"], {"0": "sport"})
            self.assertEqual({p.name for p in bundle.iterdir()}, {"model", "cache-inventory.json"})

    def test_predictions_are_used_directly_and_stale_text_is_rejected(self):
        from resolution_classification.runner import classify_records
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = {"RM/1103/37/2024": {"text_raw": "text"}}
            predictions = [{"id": "RM/1103/37/2024", "text": "text", "category": "sport", "confidence": 0.543216,
                            "second_confidence": 0.234567, "margin": 0.308649, "entropy": 1.234567}]
            with patch("resolution_classification.runner.load_bundle", return_value=(root, {"id2label": {"0": "sport"}})), \
                    patch("resolution_classification.inference.run_classification", return_value=predictions):
                decision = classify_records(records, root, root)["RM/1103/37/2024"]
                self.assertEqual(decision["category"], "sport")
                self.assertEqual(decision["source"], "model")
                self.assertEqual(decision["status"], "classified")
                self.assertEqual(decision["prediction"]["confidence"], 0.54)
                self.assertEqual(decision["prediction"]["second_confidence"], 0.23)
                self.assertEqual(decision["prediction"]["margin"], 0.31)
                self.assertEqual(decision["prediction"]["entropy"], 1.23)
                self.assertEqual(predictions[0]["confidence"], 0.543216)
                self.assertEqual(predictions[0]["margin"], 0.308649)
                records["RM/1103/37/2024"]["text_raw"] = "changed"
                with self.assertRaisesRegex(ValueError, "stale_prediction"):
                    classify_records(records, root, root)

    def test_symlink_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.tar.gz"
            checksum = make_bundle(archive, symlink=True)
            with self.assertRaisesRegex(ValueError, "regular bundle file"):
                load_bundle(archive.as_uri(), root / "cache", checksum)

    def test_incomplete_predictions_stop_pipeline(self):
        from resolution_classification.runner import classify_records
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("resolution_classification.runner.load_bundle", return_value=(root, {})), \
                    patch("resolution_classification.inference.run_classification", return_value=[]):
                with self.assertRaisesRegex(ValueError, "exactly once"):
                    classify_records({"a": {"id": "a", "text_raw": "text"}}, root, root)

    def test_incremental_reuses_only_matching_text_and_model(self):
        from resolution_classification.runner import classify_records, text_hash
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = {"a": {"text_raw": "old"}, "b": {"text_raw": "new"}}
            old = {"category": "sport", "source": "model", "status": "classified",
                   "model_url": "model", "model_sha256": "checksum",
                   "text_sha256": text_hash("old"),
                   "prediction": {"category": "sport", "confidence": 0.8,
                                  "second_category": "culture", "second_confidence": 0.1,
                                  "margin": 0.7, "entropy": 0.2}}
            predictions = [{"id": "b", "text": "new", "category": "sport", "confidence": 0.9}]
            with patch("resolution_classification.runner.load_bundle",
                       return_value=(root, {"id2label": {"0": "sport"}})) as load, \
                 patch("resolution_classification.inference.run_classification",
                       return_value=predictions) as infer:
                result = classify_records(records, root, root, "model", "checksum", previous={"a": old})
                self.assertEqual(result["a"], old)
                self.assertEqual(result["b"]["text_sha256"], text_hash("new"))
                self.assertEqual(infer.call_args.kwargs["selected_ids"], {"b"})
                load.assert_called_once()

                infer.reset_mock()
                load.reset_mock()
                classify_records({"a": records["a"]}, root, root, "model", "checksum", previous={"a": old})
                infer.assert_not_called()
                load.assert_not_called()
                self.assertEqual((root / "classifications.jsonl").read_text(), "")

    def test_changed_text_and_model_require_inference(self):
        from resolution_classification.runner import reusable, text_hash
        record = {"text_raw": "old"}
        old = {"category": "sport", "source": "model", "status": "classified",
               "model_url": "model", "model_sha256": "checksum",
               "text_sha256": text_hash("old"),
               "prediction": {"category": "sport", "confidence": 0.8,
                              "second_category": "culture", "second_confidence": 0.1,
                              "margin": 0.7, "entropy": 0.2}}
        self.assertTrue(reusable(old, record, "model", "checksum"))
        self.assertFalse(reusable(old, {"text_raw": "changed"}, "model", "checksum"))
        self.assertFalse(reusable(old, record, "model", "new-checksum"))
        self.assertFalse(reusable({**old, "prediction": {}}, record, "model", "checksum"))


if __name__ == "__main__":
    unittest.main()
