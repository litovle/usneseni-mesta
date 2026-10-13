"""Classify raw resolutions with a cached, checksum-pinned model URL.

All model metadata and manual decisions come from the cached bundle. The
published v1 weights-only release uses the matching annotations shipped with
this pipeline. No classifier repository checkout or package is required.
"""

import json
from pathlib import Path

from . import DEFAULT_SHA256, DEFAULT_URL
from .bundle import load_bundle
from .decisions import attach, load_records


def classify_records(records, phase1, output, url=DEFAULT_URL, checksum=DEFAULT_SHA256, cache=Path(".cache/resolution-classifier")):
    """Return reviewed decisions by ID and write model evidence/review queues.

    Overrides take precedence; ambiguous resolutions have no effective category.
    Coverage gaps and stale manual decisions raise before analysis outputs are
    written. Inference runs on CPU, CUDA or MPS when available.
    """
    from .inference import run_classification

    bundle, manifest = load_bundle(url, cache, checksum)
    predictions = run_classification(bundle / "model", phase1, output / "classifications.jsonl")
    indexed = {row["id"]: row for row in predictions}
    if len(indexed) != len(predictions) or indexed.keys() != records.keys():
        raise ValueError("Classifier predictions must cover each input resolution exactly once")
    if any(row["category"] not in manifest["labels"] for row in predictions):
        raise ValueError("Model categories do not match the bundled taxonomy")
    enriched = attach(records, indexed,
                      load_records(bundle / "data/manual-overrides-v1.jsonl"),
                      load_records(bundle / "data/manual-review-required-v1.jsonl"),
                      manifest["model_version"], manifest["taxonomy_version"])
    for row in enriched:
        decision = row["classification"]
        if decision["status"] not in {"classified", "manual_review_required"}:
            raise ValueError(f"Resolution {row['id']} needs attention: {decision['status']}")
        decision["model_url"] = url
        decision["model_sha256"] = checksum
    (output / "reviewed-classifications.jsonl").write_text(
        "".join(json.dumps({"id": row["id"], **row["classification"]}, ensure_ascii=False) + "\n"
                for row in enriched), encoding="utf-8")
    return {row["id"]: row["classification"] for row in enriched}
