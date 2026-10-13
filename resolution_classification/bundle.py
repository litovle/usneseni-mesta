"""Download and cache a model bundle without another repository checkout."""

import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlopen

MODEL_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors")


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_bundle(url, cache, checksum):
    """Load a URL's SHA-256-pinned archive, reusing verified cached files.

    Cache directories are named by archive checksum. Only model and tokenizer
    files are extracted. Returned values are the bundle directory and model
    config, whose id2label mapping defines the categories.
    """
    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("Classifier SHA-256 must contain 64 lowercase hexadecimal characters")
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / checksum
    inventory = destination / "cache-inventory.json"
    if inventory.is_file():
        hashes = json.loads(inventory.read_text(encoding="utf-8"))
        if all(name in hashes and (destination / name).is_file()
               and file_hash(destination / name) == hashes[name]
               for name in (f"model/{file}" for file in MODEL_FILES)):
            return destination, json.loads((destination / "model/config.json").read_text(encoding="utf-8"))
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
            wanted = [f"model/{name}" for name in MODEL_FILES]
            for name in wanted:
                member = bundle.getmember(name)
                if not member.isfile():
                    raise ValueError(f"Expected regular bundle file: {name}")
                path = extracted / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as source, path.open("wb") as stream:
                    shutil.copyfileobj(source, stream)
        files = [f"model/{name}" for name in MODEL_FILES]
        hashes = {name: file_hash(extracted / name) for name in files}
        (extracted / "cache-inventory.json").write_text(json.dumps(hashes), encoding="utf-8")
        extracted.rename(destination)
    return destination, json.loads((destination / "model/config.json").read_text(encoding="utf-8"))
