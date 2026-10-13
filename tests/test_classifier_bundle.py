import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from resolution_classification.bundle import METADATA_FILES, MODEL_FILES, load_bundle


def make_bundle(path, metadata=True, symlink=False):
    with tarfile.open(path, "w:gz") as archive:
        files = [f"model/{name}" for name in MODEL_FILES]
        if metadata:
            files += list(METADATA_FILES)
        for name in files:
            body = json.dumps({"model_version": "1.0.0", "taxonomy_version": "v7", "labels": ["sport"]}).encode() if name == "manifest.json" else b"{}"
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
            bundle, manifest = load_bundle(archive.as_uri(), root / "cache", checksum)
            self.assertEqual(manifest["model_version"], "1.0.0")
            self.assertTrue((bundle / "model/model.safetensors").is_file())
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

    def test_only_pinned_weights_only_release_can_use_packaged_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bundle.tar.gz"
            checksum = make_bundle(archive, metadata=False)
            with self.assertRaisesRegex(ValueError, "Custom classifier"):
                load_bundle(archive.as_uri(), root / "cache", checksum)
            with patch("resolution_classification.bundle.DEFAULT_SHA256", checksum):
                bundle, manifest = load_bundle(archive.as_uri(), root / "cache", checksum)
            self.assertEqual(manifest["taxonomy_version"], "v7")
            self.assertTrue((bundle / "data/manual-overrides-v1.jsonl").is_file())

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
