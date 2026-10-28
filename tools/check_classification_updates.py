#!/usr/bin/env python3
"""Check whether stored classifications need inference for the current model."""

import argparse
import json
import os
from pathlib import Path

from resolution_classification.runner import reusable


def count_pending(phase1: Path, analyzed: Path, url: str, checksum: str) -> int:
    pending = 0
    for source in phase1.glob("*.json"):
        raw = json.loads(source.read_text(encoding="utf-8"))
        target = analyzed / source.name
        classification = None
        if target.is_file():
            try:
                saved = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(saved, dict) and saved.get("id") == raw["id"]:
                    classification = saved.get("classification")
            except (OSError, ValueError):
                pass
        if not reusable(classification, raw, url, checksum):
            pending += 1
    return pending


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1", type=Path, default=Path("work/phase1"))
    parser.add_argument("--analyzed", type=Path, default=Path("work/phase3"))
    parser.add_argument("--model-url", required=True)
    parser.add_argument("--model-sha256", required=True)
    args = parser.parse_args()
    pending = count_pending(args.phase1, args.analyzed, args.model_url, args.model_sha256)
    print(f"Resolutions needing classification: {pending}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"changed={'true' if pending else 'false'}\n")


if __name__ == "__main__":
    main()
