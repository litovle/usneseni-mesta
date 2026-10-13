"""Download and cache a model bundle without another repository checkout."""

import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

from . import DEFAULT_SHA256


MODEL_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors")
METADATA_FILES = ("manifest.json", "taxonomy/v7.md", "data/manual-overrides-v1.jsonl",
                  "data/manual-review-required-v1.jsonl", "MODEL_LICENSE.md", "DATA_LICENSE.md")


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_bundle(url, cache, checksum):
    """Load a URL's SHA-256-pinned archive, reusing verified cached files.

    Cache directories are named by archive checksum. Custom releases must
    include model files, manifest, taxonomy, annotations and license notices;
    only the known v1 weights-only release uses packaged metadata. Returned
    values are the extracted bundle directory and its manifest dictionary.
    """
    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("Classifier SHA-256 must contain 64 lowercase hexadecimal characters")
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / checksum
    inventory = destination / "cache-inventory.json"
    if inventory.is_file():
        hashes = json.loads(inventory.read_text(encoding="utf-8"))
        if hashes and all((destination / name).is_file() and file_hash(destination / name) == expected
                          for name, expected in hashes.items()):
            return destination, json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        raise ValueError(f"Cached classifier files are damaged: {destination}")
    with tempfile.TemporaryDirectory(dir=cache, prefix="download-") as temporary:
        root = Path(temporary)
        archive = root / "model.tar.gz"
        print(f"Downloading final classifier: {url}", flush=True)
        with urlopen(url, timeout=120) as response, archive.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        if file_hash(archive) != checksum:
            raise ValueError("Downloaded classifier checksum does not match --classifier-sha256")
        extracted = root / "bundle"
        extracted.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            names = set(bundle.getnames())
            bundled_metadata = "manifest.json" in names
            if not bundled_metadata and checksum != DEFAULT_SHA256:
                raise ValueError("Custom classifier archives must include manifest, taxonomy and manual decisions")
            wanted = [f"model/{name}" for name in MODEL_FILES]
            if bundled_metadata:
                wanted.extend(METADATA_FILES)
            for name in wanted:
                member = bundle.getmember(name)
                if not member.isfile():
                    raise ValueError(f"Expected regular bundle file: {name}")
                path = extracted / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, path.open("wb") as stream:
                    shutil.copyfileobj(source, stream)
            if not bundled_metadata:
                # The published v1 weights-only asset has matching, pinned
                # annotations distributed with this pipeline.
                metadata = Path(__file__).parent / "final-v1"
                for name in METADATA_FILES:
                    path = extracted / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(metadata / name, path)
        files = [f"model/{name}" for name in MODEL_FILES] + list(METADATA_FILES)
        hashes = {name: file_hash(extracted / name) for name in files}
        (extracted / "cache-inventory.json").write_text(json.dumps(hashes), encoding="utf-8")
        extracted.rename(destination)
    return destination, json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
