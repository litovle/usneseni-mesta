"""Classify raw resolutions using a cached, checksum-pinned model URL."""

import hashlib
from pathlib import Path

from . import DEFAULT_SHA256, DEFAULT_URL
from .bundle import load_bundle


SCORE_FIELDS = {"confidence", "second_confidence", "margin", "entropy"}


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reusable(classification, record, url, checksum):
    if not isinstance(classification, dict) or not isinstance(record.get("text_raw"), str):
        return False
    prediction = classification.get("prediction")
    return (classification.get("source") == "model"
            and classification.get("status") == "classified"
            and classification.get("model_url") == url
            and classification.get("model_sha256") == checksum
            and classification.get("text_sha256") == text_hash(record["text_raw"])
            and isinstance(classification.get("category"), str)
            and isinstance(prediction, dict)
            and prediction.get("category") == classification["category"]
            and isinstance(prediction.get("second_category"), str)
            and all(isinstance(prediction.get(key), (int, float))
                    for key in SCORE_FIELDS))


def classify_records(records, phase1, output, url=DEFAULT_URL, checksum=DEFAULT_SHA256,
                     cache=Path(".cache/resolution-classifier"), previous=None):
    """Return model predictions by ID, preserving scores and release identity.

    Scores in attached classifications are rounded to two decimal places; the
    ignored inference reports retain full precision. Coverage gaps and stale
    input text raise before analysis outputs are written.
    Inference runs on CPU, CUDA or MPS when available.
    """
    from .inference import run_classification, write_reports

    previous = previous or {}
    result = {rid: previous[rid] for rid, record in records.items()
              if rid in previous and reusable(previous[rid], record, url, checksum)}
    pending = set(records) - set(result)
    report = output / "classifications.jsonl"
    if not pending:
        write_reports([], "reused", phase1, report)
        return result

    bundle, config = load_bundle(url, cache, checksum)
    if len(pending) == len(records) and not previous:
        predictions = run_classification(bundle / "model", phase1, report)
    else:
        predictions = run_classification(bundle / "model", phase1, report, selected_ids=pending)
    indexed = {row["id"]: row for row in predictions}
    if len(indexed) != len(predictions) or indexed.keys() != pending:
        raise ValueError("Classifier predictions must cover each input resolution exactly once")
    labels = set(config["id2label"].values())
    if any(row["category"] not in labels for row in predictions):
        raise ValueError("Model categories do not match the model configuration")
    for rid in pending:
        record = records[rid]
        prediction = indexed[rid]
        if record.get("text_raw") != prediction.get("text"):
            raise ValueError(f"Resolution {rid} needs attention: stale_prediction")
        result[rid] = {
            "category": prediction["category"],
            "source": "model",
            "status": "classified",
            "model_url": url,
            "model_sha256": checksum,
            "text_sha256": text_hash(record["text_raw"]),
            "prediction": {
                key: round(value, 2) if key in SCORE_FIELDS else value
                for key, value in prediction.items() if key not in {"id", "text"}
            },
        }
    return result
