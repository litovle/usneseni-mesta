import json
from pathlib import Path


def load_records(path):
    path = Path(path)
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{path}: expected a list of records")
    indexed = {}
    for record in records:
        rid = record["id"]
        if rid in indexed:
            raise ValueError(f"{path}: duplicate ID {rid}")
        indexed[rid] = record
    return indexed


def attach(records, predictions, overrides, reviews, model_version, taxonomy_version):
    """Keep raw model evidence, prefer human decisions, abstain on known ambiguity.

    Manual decisions are tied to exact resolution text, since IDs can be reused
    when rerunning extraction or correcting source documents.
    """
    result = []
    for rid, record in records.items():
        row = dict(record)
        prediction = predictions.get(rid)
        if prediction is None:
            row["classification"] = {"status": "missing_prediction", "category": None}
            result.append(row)
            continue
        decision = {
            "model_version": model_version,
            "taxonomy_version": taxonomy_version,
            "category": prediction["category"],
            "source": "model",
            "status": "classified",
            "prediction": {key: value for key, value in prediction.items() if key not in {"id", "text"}},
        }
        raw_text = record.get("text_raw")
        if raw_text is not None and raw_text != prediction.get("text"):
            decision.update(category=None, source=None, status="stale_prediction")
        else:
            manual = reviews.get(rid) or overrides.get(rid)
            if manual:
                if not manual.get("text") or manual["text"] != prediction.get("text"):
                    decision.update(category=None, source=None, status="stale_manual_decision")
                elif rid in reviews:
                    decision.update(category=None, source="manual_review", status="manual_review_required",
                                    reason=manual.get("reason"))
                else:
                    decision.update(category=manual["category"], source="manual_override")
        row["classification"] = decision
        result.append(row)
    return result
