"""Compact on-disk representation of token-to-document search postings."""

import json
from pathlib import Path


def compact_index(index: dict[str, list[str]]) -> dict:
    """Store each document ID once; postings reference its zero-based position."""
    ids = sorted({record_id for hits in index.values() for record_id in hits})
    positions = {record_id: position for position, record_id in enumerate(ids)}
    return {
        "ids": ids,
        "tokens": {
            token: [positions[record_id] for record_id in index[token]]
            for token in sorted(index)
        },
    }


def write_compact_index(path: Path, index: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(compact_index(index), ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
