"""Classify raw resolutions using a cached, checksum-pinned model URL."""

from pathlib import Path

from . import DEFAULT_SHA256, DEFAULT_URL
from .bundle import load_bundle


SCORE_FIELDS = {"confidence", "second_confidence", "margin", "entropy"}


def classify_records(records, phase1, output, url=DEFAULT_URL, checksum=DEFAULT_SHA256, cache=Path(".cache/resolution-classifier")):
    """Return model predictions by ID, preserving scores and release identity.

    Scores in attached classifications are rounded to two decimal places; the
    ignored inference reports retain full precision. Coverage gaps and stale
    input text raise before analysis outputs are written.
    Inference runs on CPU, CUDA or MPS when available.
    """
    from .inference import run_classification

    bundle, config = load_bundle(url, cache, checksum)
    predictions = run_classification(bundle / "model", phase1, output / "classifications.jsonl")
    indexed = {row["id"]: row for row in predictions}
    if len(indexed) != len(predictions) or indexed.keys() != records.keys():
        raise ValueError("Classifier predictions must cover each input resolution exactly once")
    labels = set(config["id2label"].values())
    if any(row["category"] not in labels for row in predictions):
        raise ValueError("Model categories do not match the model configuration")
    result = {}
    for rid, record in records.items():
        prediction = indexed[rid]
        if record.get("text_raw") != prediction.get("text"):
            raise ValueError(f"Resolution {rid} needs attention: stale_prediction")
        result[rid] = {
            "category": prediction["category"],
            "source": "model",
            "status": "classified",
            "model_url": url,
            "model_sha256": checksum,
            "prediction": {
                key: round(value, 2) if key in SCORE_FIELDS else value
                for key, value in prediction.items() if key not in {"id", "text"}
            },
        }
    return result
