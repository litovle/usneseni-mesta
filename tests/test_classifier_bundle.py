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
            predictions = [{"id": "RM/1103/37/2024", "text": "text", "category": "sport", "confidence": 0.54}]
            with patch("resolution_classification.runner.load_bundle", return_value=(root, {"id2label": {"0": "sport"}})), \
                    patch("resolution_classification.inference.run_classification", return_value=predictions):
                decision = classify_records(records, root, root)["RM/1103/37/2024"]
                self.assertEqual(decision["category"], "sport")
                self.assertEqual(decision["source"], "model")
                self.assertEqual(decision["status"], "classified")
                self.assertEqual(decision["prediction"]["confidence"], 0.54)
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


if __name__ == "__main__":
    unittest.main()
