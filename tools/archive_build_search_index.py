#!/usr/bin/env python3
"""Build a public fulltext index for Litovel ZM archive records."""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from collections import defaultdict
from pathlib import Path

try:
    from archive_zm_common import read_json, write_json
    from search_index_format import write_compact_index
except ImportError:
    from tools.archive_zm_common import read_json, write_json
    from tools.search_index_format import write_compact_index


WORD_RE = re.compile(r"[a-z0-9]{3,}")
INDEXABLE_QUALITY_FLAGS = {"text_ok", "short_text"}
SKIP_REASONS = ("not_usneseni", "no_search_text", "bad_quality_flag")


def normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(char for char in text if not unicodedata.combining(char))


def record_year(record: dict) -> str:
    year = record.get("year")
    if isinstance(year, int):
        return str(year)
    if isinstance(year, str) and year.isdigit():
        return year

    date = record.get("date")
    if isinstance(date, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return date[:4]

    return "unknown"


def year_sort_key(year: str) -> tuple[int, int | str]:
    if year.isdigit():
        return (0, int(year))
    return (1, year)


def archive_sort_key(record: dict) -> tuple:
    return (
        year_sort_key(record_year(record)),
        record.get("date") or "",
        record.get("meeting_no") if record.get("meeting_no") is not None else 999999,
        record.get("id") or "",
    )


def archive_permalink(record: dict) -> str:
    return f"/usneseni/archiv/{record.get('id')}/"


def index_text(record: dict) -> str:
    return " ".join(
        str(part)
        for part in (
            record.get("id") or "",
            record.get("title") or "",
            record.get("date") or "",
            record.get("period") or "",
            record.get("organ") or "",
            record.get("kind") or "",
            record.get("search_text") or "",
        )
        if part
    )


def public_record(record: dict) -> dict:
    output = {
        "id": record.get("id"),
        "type": record.get("type") or "archive_document",
        "legacy": True,
        "org": record.get("org") or "ZM",
        "organ": record.get("organ") or "Zastupitelstvo města Litovel",
        "title": record.get("title"),
        "date": record.get("date"),
        "year": record.get("year"),
        "period": record.get("period"),
        "meeting_no": record.get("meeting_no"),
        "kind": record.get("kind"),
        "search_text": record.get("search_text") or "",
        "display_text": record.get("display_text") or record.get("search_text") or "",
        "source_url": record.get("source_url"),
        "original_file_url": record.get("original_file_url"),
        "file_type": record.get("file_type"),
        "extraction_method": record.get("extraction_method") or "none",
        "ocr_used": bool(record.get("ocr_used")),
        "text_quality": record.get("text_quality") or {},
        "permalink": archive_permalink(record),
    }

    for key in (
        "parent_document_id",
        "ordinal",
        "resolution_no",
        "source_span",
        "split_method",
        "split_confidence",
    ):
        if key in record:
            output[key] = record.get(key)

    return output


def skip_reason(record: dict) -> str | None:
    record_type = record.get("type")
    if record_type not in {"archive_document", "archive_resolution"} or record.get("kind") != "usneseni":
        return "not_usneseni"

    if not (record.get("search_text") or "").strip():
        return "no_search_text"

    if record_type == "archive_document":
        quality_flag = (record.get("text_quality") or {}).get("quality_flag")
        if quality_flag not in INDEXABLE_QUALITY_FLAGS:
            return "bad_quality_flag"

    return None


def indexable_records(records: list[dict], split_parent_ids: set[str] | None = None) -> tuple[list[dict], dict]:
    split_parent_ids = split_parent_ids or set()
    indexed = []
    skipped = Counter({reason: 0 for reason in SKIP_REASONS})
    skipped_ids: dict[str, list[str]] = {reason: [] for reason in SKIP_REASONS}
    skipped_split_parents = []

    for record in records:
        if record.get("type") == "archive_document" and record.get("id") in split_parent_ids:
            skipped_split_parents.append(record.get("id") or "")
            continue
        reason = skip_reason(record)
        if reason:
            skipped[reason] += 1
            skipped_ids[reason].append(record.get("id") or "")
            continue
        indexed.append(public_record(record))

    indexed.sort(key=archive_sort_key)
    for reason in skipped_ids:
        skipped_ids[reason] = sorted(value for value in skipped_ids[reason] if value)

    return indexed, {
        "indexed": len(indexed),
        "skipped": dict(skipped),
        "skipped_ids": skipped_ids,
        "skipped_split_parents": sorted(value for value in skipped_split_parents if value),
    }


def build_index(records: list[dict]) -> dict:
    index: dict[str, set[str]] = defaultdict(set)

    for record in records:
        record_id = record["id"]
        text = normalize(index_text(record))
        for word in WORD_RE.findall(text):
            index[word].add(record_id)
            for i in range(4, len(word)):
                index[word[:i]].add(record_id)

    return {key: sorted(value) for key, value in sorted(index.items())}


def group_by_year(records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record_year(record)].append(record)
    return {
        year: sorted(items, key=archive_sort_key)
        for year, items in sorted(grouped.items(), key=lambda item: year_sort_key(item[0]))
    }


def build_payload(
    records: list[dict],
    resolutions: list[dict] | None = None,
    promoted_document_ids: set[str] | None = None,
) -> tuple[dict[str, list[dict]], dict]:
    resolutions = resolutions or []
    promoted_document_ids = promoted_document_ids or set()
    records = [
        record
        for record in records
        if record.get("id") not in promoted_document_ids
    ]
    resolutions = [
        record
        for record in resolutions
        if record.get("parent_document_id") not in promoted_document_ids
    ]
    split_parent_ids = {
        record.get("parent_document_id")
        for record in resolutions
        if record.get("type") == "archive_resolution" and record.get("parent_document_id")
    }
    indexed_documents, document_report = indexable_records(records, split_parent_ids)
    indexed_resolutions, resolution_report = indexable_records(resolutions)
    indexed = sorted(indexed_documents + indexed_resolutions, key=archive_sort_key)
    report = {
        "indexed": len(indexed),
        "indexed_archive_resolutions": len(indexed_resolutions),
        "fallback_archive_documents": len(indexed_documents),
        "skipped_promoted_documents": len(promoted_document_ids),
        "skipped_split_parents": len(document_report["skipped_split_parents"]),
        "skipped_split_parent_ids": document_report["skipped_split_parents"],
        "skipped": {
            reason: document_report["skipped"][reason] + resolution_report["skipped"][reason]
            for reason in SKIP_REASONS
        },
        "skipped_ids": {
            reason: sorted(document_report["skipped_ids"][reason] + resolution_report["skipped_ids"][reason])
            for reason in SKIP_REASONS
        },
    }
    by_year = group_by_year(indexed)
    report["indexed_by_year"] = {
        year: len(items)
        for year, items in by_year.items()
    }
    report["indexed_ids"] = [record["id"] for record in indexed]
    return by_year, report


def read_promoted_document_ids(paths: list[Path]) -> set[str]:
    promoted: set[str] = set()
    for path in paths:
        report = read_json(path, {})
        if not isinstance(report, dict):
            continue
        values = report.get("promoted_document_ids") or []
        if isinstance(values, list):
            promoted.update(value for value in values if isinstance(value, str))
    return promoted


def read_json_lists(paths: list[Path]) -> list[dict]:
    combined: list[dict] = []
    for path in paths:
        records = read_json(path, [])
        if not isinstance(records, list):
            raise SystemExit(f"Archive input must be a JSON list: {path}")
        combined.extend(records)
    return combined


def write_search_index(by_year: dict[str, list[dict]], output: Path) -> dict:
    meta = {}
    (output / "index").mkdir(parents=True, exist_ok=True)
    (output / "data").mkdir(parents=True, exist_ok=True)

    for year, items in by_year.items():
        write_compact_index(output / "index" / f"{year}.json", build_index(items))
        write_json(output / "data" / f"{year}.json", items)
        meta[year] = {"count": len(items)}

    write_json(output / "meta.json", meta)
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=[Path("work/archive_zm/archive_documents.json")],
        help="One or more archive_documents.json inputs.",
    )
    parser.add_argument(
        "--resolutions",
        type=Path,
        nargs="*",
        default=[Path("work/archive_zm/archive_resolutions.json")],
        help="Optional archive_resolutions.json child-record inputs.",
    )
    parser.add_argument(
        "--promoted-report",
        type=Path,
        nargs="*",
        default=[],
        help="Optional archive_current_promoted.json reports. Promoted documents are excluded from archive output.",
    )
    parser.add_argument("--output", type=Path, default=Path("work/archive_zm/search_index"))
    parser.add_argument("--report", type=Path, default=Path("work/archive_zm/search_index_report.json"))
    args = parser.parse_args()

    records = read_json_lists(args.input)
    resolutions = read_json_lists(args.resolutions)
    promoted_document_ids = read_promoted_document_ids(args.promoted_report)

    by_year, report = build_payload(records, resolutions, promoted_document_ids)
    write_search_index(by_year, args.output)
    write_json(args.report, report)

    print(f"Archive search index written: {args.output}")
    print(f"Indexed archive records: {report['indexed']}")
    print(f"Archive resolutions: {report['indexed_archive_resolutions']}")
    print(f"Fallback archive documents: {report['fallback_archive_documents']}")
    print("Skipped:", ", ".join(f"{key}={report['skipped'][key]}" for key in SKIP_REASONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
