#!/usr/bin/env python3
"""Local inference on Phase 1 text using an extracted classifier model.

The URL download and checksum validation are handled by
resolution_classification.bundle. Softmax scores are uncalibrated model scores.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def entropy(probs):
    return -sum(p * math.log(p + 1e-12) for p in probs)


def load_phase1(path: Path):
    rows = []
    for file in sorted(path.glob("*.json")):
        try:
            obj = json.loads(file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"WARN: cannot read {file}: {e}")
            continue

        rid = obj.get("id")
        text = obj.get("text_raw")
        if rid and text:
            rows.append({
                "id": rid,
                "text": text,
                "source_file": str(file),
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--model",
        type=Path,
        default=Path("work/released-v1/model"),
    )
    ap.add_argument(
        "--phase1",
        type=Path,
        default=Path("work/phase1"),
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("work/classifier/classifications.jsonl"),
    )
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--include-probabilities", action="store_true")
    args = ap.parse_args()

    run_classification(args.model, args.phase1, args.output, args.batch_size, args.include_probabilities)


def run_classification(model_path, phase1, output, batch_size=32, include_probabilities=False):
    """Return raw predictions and write counts plus a low-margin review queue.

    Inputs are Phase 1 JSON files with id and text_raw. All model/tokenizer files
    must exist at model_path; this function never downloads Hugging Face files.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    rows = load_phase1(phase1)
    if not rows:
        raise ValueError(f"No resolutions found in {phase1}")
    print(f"Resolutions: {len(rows)}")

    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(str(model_path), local_files_only=True)

    if torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    print(f"Device: {device}")
    model.to(device)
    model.eval()

    id2label = {int(k): v for k, v in model.config.id2label.items()}
    counts = Counter()
    results = []

    with torch.inference_mode():
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            encoded = tokenizer(
                [r["text"] for r in batch],
                padding=True,
                truncation=True,
                max_length=510,
                return_tensors="pt",
            )
            encoded = {k: v.to(device) for k, v in encoded.items()}

            logits = model(**encoded).logits
            probs = torch.softmax(logits, dim=-1).cpu()

            for row, p in zip(batch, probs):
                values, indices = torch.topk(p, k=2)
                p_list = [float(x) for x in p]

                top1 = int(indices[0])
                top2 = int(indices[1])
                category = id2label[top1]
                counts[category] += 1

                result = {
                    "id": row["id"],
                    "category": category,
                    "confidence": float(values[0]),
                    "second_category": id2label[top2],
                    "second_confidence": float(values[1]),
                    "margin": float(values[0] - values[1]),
                    "entropy": entropy(p_list),
                    # Keep text in every output. This makes review queues
                    # self-contained and avoids another phase1 lookup.
                    "text": row["text"],
                }

                if include_probabilities:
                    result["probabilities"] = {
                        id2label[i]: p_list[i]
                        for i in range(len(p_list))
                    }

                results.append(result)

            done = min(start + batch_size, len(rows))
            if done % 320 == 0 or done == len(rows):
                print(f"  {done}/{len(rows)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n",
        encoding="utf-8",
    )

    summary = {
        "model": str(model_path),
        "phase1": str(phase1),
        "count": len(results),
        "category_counts": dict(sorted(counts.items())),
        "confidence": {
            "below_0_50": sum(r["confidence"] < 0.50 for r in results),
            "below_0_70": sum(r["confidence"] < 0.70 for r in results),
            "below_0_90": sum(r["confidence"] < 0.90 for r in results),
            "margin_below_0_10": sum(r["margin"] < 0.10 for r in results),
            "margin_below_0_20": sum(r["margin"] < 0.20 for r in results),
        },
    }

    summary_path = output.with_name("classification-summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    review = sorted(results, key=lambda r: (r["margin"], r["confidence"]))
    review_path = output.with_name("review-queue.jsonl")
    review_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in review) + "\n",
        encoding="utf-8",
    )

    print("\nCategory counts:")
    for label, count in sorted(counts.items()):
        print(f"  {label:18} {count}")

    print(f"\nClassifications: {output}")
    print(f"Summary:         {summary_path}")
    print(f"Review queue:    {review_path}")
    return results


if __name__ == "__main__":
    main()
