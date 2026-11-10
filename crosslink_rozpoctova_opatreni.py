#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Propojení rozpočtových opatření s usneseními.

Vstup:
  - phase3/usneseni.json
  - adresář JSON souborů z parse_rozpoctova_opatreni.py

Výstup:
  - obohacená kopie usneseni.json
  - obohacené kopie JSON souborů rozpočtových opatření
  - budget_change_index.json
  - stats.json

Použití:
  python crosslink_rozpoctova_opatreni.py \
    --resolutions work/phase3/usneseni.json \
    --opatreni work/rozpoctova-opatreni \
    --output work/rozpoctova-opatreni-linked
"""

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path

from static_export.ro_summary import budget_change_groups_from_opatreni
from tools.resolution_ids import parse_resolution_id as resolution_parts



BUDGET_CHANGE_ID_RE = re.compile(
    r"\b(?:RZ\s*)?(?P<id>\d{1,4}\s*/\s*\d{4}\s*/\s*(?:RM|ZM))\b",
    re.IGNORECASE,
)

BUDGET_CHANGE_RANGE_RE = re.compile(
    r"\b(?P<start>\d{1,4})\s*/\s*(?P<year>\d{4})\s*/\s*(?P<organ>RM|ZM)"
    r"\s*(?:až|az|–|-)\s*"
    r"(?P<end>\d{1,4})\s*/\s*(?P=year)\s*/\s*(?P=organ)\b",
    re.IGNORECASE,
)

DIRECTIVE_REFERENCE_BEFORE_RE = re.compile(
    r"(?:sm[eě]rnic[ei]|sm[eě]rnice\s+\w+)\s+(?:č\.?\s*)?$",
    re.IGNORECASE,
)


def normalize_budget_change_id(value: str) -> str:
    return re.sub(r"\s+", "", value.upper())


def is_directive_reference_context(text: str, match_start: int) -> bool:
    before = text[max(0, match_start - 40):match_start]
    return bool(DIRECTIVE_REFERENCE_BEFORE_RE.search(before))


def parse_resolution_id(value: str):
    parts = resolution_parts(value)
    if parts is None:
        return None
    return parts.organ, parts.number, parts.meeting, parts.year


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def resolution_text(resolution: dict) -> str:
    parts = []

    if resolution.get("subject"):
        parts.append(resolution["subject"])

    for item in resolution.get("items") or []:
        if item.get("text"):
            parts.append(item["text"])

    if resolution.get("tail"):
        parts.append(resolution["tail"])

    return " ".join(" ".join(part.split()) for part in parts)


def extract_budget_change_mentions(text: str, known_ids: set[str]):
    mentions = {}

    for match in BUDGET_CHANGE_RANGE_RE.finditer(text):
        start = int(match.group("start"))
        end = int(match.group("end"))
        year = match.group("year")
        organ = match.group("organ").upper()

        if start > end:
            continue

        for number in range(start, end + 1):
            budget_change_id = f"{number}/{year}/{organ}"
            if budget_change_id in known_ids:
                mentions[budget_change_id] = "range"

    for match in BUDGET_CHANGE_ID_RE.finditer(text):
        if is_directive_reference_context(text, match.start()):
            continue
        budget_change_id = normalize_budget_change_id(match.group("id"))
        if budget_change_id not in known_ids:
            continue
        mentions.setdefault(budget_change_id, "direct")

    return mentions


def build_budget_change_index(opatreni_list: list[dict]):
    index = {}

    for opatreni in opatreni_list:
        summary_by_budget_change_id = {
            group["budget_change_id"]: group
            for group in budget_change_groups_from_opatreni(opatreni)
        }
        for section in opatreni.get("sections") or []:
            section_type = section.get("type")
            for row_number, row in enumerate(section.get("rows") or [], start=1):
                budget_change_id = row.get("budget_change_id")
                if not budget_change_id:
                    continue

                entry = index.setdefault(
                    budget_change_id,
                    {
                        "opatreni_id": opatreni["id"],
                        "rows": [],
                        "resolution_ids": [],
                        "plain_title": "",
                        "affected_place": "",
                    },
                )
                if not entry.get("plain_title"):
                    entry["plain_title"] = str(
                        summary_by_budget_change_id.get(budget_change_id, {}).get("title") or ""
                    )
                if not entry.get("affected_place"):
                    entry["affected_place"] = str(
                        summary_by_budget_change_id.get(budget_change_id, {}).get("affected_place") or ""
                    )
                entry["rows"].append({
                    "section_type": section_type,
                    "row_number": row_number,
                    "amount": row.get("amount"),
                    "amount_value": row.get("amount_value"),
                    "description": row.get("description"),
                })

    return index


def resolve_resolution_id(raw_id: str, by_id: dict, by_resolution_key: dict):
    if raw_id in by_id:
        return raw_id, None

    parts = resolution_parts(raw_id)
    if parts is None or parts.scheme == "usneseni.cz":
        return None, None

    key = (parts.organ, parts.number, parts.meeting)
    candidates = [
        candidate for candidate in by_resolution_key.get(key, [])
        if (candidate_parts := resolution_parts(candidate)) and candidate_parts.scheme == parts.scheme
    ]
    if len(candidates) != 1:
        return None, None

    candidate = candidates[0]
    candidate_parsed = parse_resolution_id(candidate)
    if not candidate_parsed:
        return None, None

    _, _, _, candidate_year = candidate_parsed
    if abs(candidate_year - parts.year) > 20:
        return None, None

    return candidate, {
        "raw": raw_id,
        "resolved": candidate,
        "reason": "unique_matching_resolution_number_and_meeting",
    }


def add_unique_list_item(items: list, item: dict, key_fields: tuple[str, ...]):
    key = tuple(item.get(field) for field in key_fields)
    for existing in items:
        if tuple(existing.get(field) for field in key_fields) == key:
            return
    items.append(item)


def crosslink(resolutions: list[dict], opatreni_list: list[dict]):
    linked_resolutions = deepcopy(resolutions)
    linked_opatreni = deepcopy(opatreni_list)

    by_id = {resolution["id"]: resolution for resolution in linked_resolutions}
    by_resolution_key = {}
    for resolution in linked_resolutions:
        parsed = parse_resolution_id(resolution["id"])
        if not parsed:
            continue
        organ, number, meeting, _ = parsed
        by_resolution_key.setdefault((organ, number, meeting), []).append(resolution["id"])

    for ids in by_resolution_key.values():
        ids.sort()

    for resolution in linked_resolutions:
        resolution["budget_change_links"] = []
        resolution["budget_opatreni_approved"] = []

    for opatreni in linked_opatreni:
        opatreni["resolution_links"] = []

    budget_change_index = build_budget_change_index(linked_opatreni)
    known_budget_change_ids = set(budget_change_index)

    stats = {
        "total_resolutions": len(linked_resolutions),
        "total_opatreni": len(linked_opatreni),
        "budget_change_ids": len(known_budget_change_ids),
        "approval_links": 0,
        "budget_change_links": 0,
        "corrected_source_resolutions": [],
        "unresolved_source_resolutions": [],
        "resolutions_with_budget_change_links": 0,
        "opatreni_with_resolution_links": 0,
    }

    # RO header -> approving resolution.
    for opatreni in linked_opatreni:
        for raw_resolution_id in opatreni.get("source_resolutions") or []:
            resolved_id, correction = resolve_resolution_id(
                raw_resolution_id,
                by_id,
                by_resolution_key,
            )

            if correction:
                correction["opatreni_id"] = opatreni["id"]
                stats["corrected_source_resolutions"].append(correction)

            if not resolved_id:
                stats["unresolved_source_resolutions"].append({
                    "opatreni_id": opatreni["id"],
                    "resolution_id": raw_resolution_id,
                })
                continue

            resolution = by_id[resolved_id]
            add_unique_list_item(
                resolution["budget_opatreni_approved"],
                {
                    "opatreni_id": opatreni["id"],
                    "source": "ro_header",
                },
                ("opatreni_id", "source"),
            )
            add_unique_list_item(
                opatreni["resolution_links"],
                {
                    "resolution_id": resolved_id,
                    "relation": "approves_opatreni",
                    "source": "ro_header",
                },
                ("resolution_id", "relation", "source"),
            )
            stats["approval_links"] += 1

    # Resolution text -> concrete RZ ids -> RO rows.
    opatreni_by_id = {opatreni["id"]: opatreni for opatreni in linked_opatreni}

    for resolution in linked_resolutions:
        mentions = extract_budget_change_mentions(
            resolution_text(resolution),
            known_budget_change_ids,
        )
        for budget_change_id, match_type in sorted(
            mentions.items(),
            key=lambda item: budget_change_sort_key(item[0]),
        ):
            index_entry = budget_change_index[budget_change_id]
            opatreni_id = index_entry["opatreni_id"]
            section_types = sorted({
                row["section_type"]
                for row in index_entry["rows"]
                if row.get("section_type")
            })
            resolution_link = {
                "budget_change_id": budget_change_id,
                "opatreni_id": opatreni_id,
                "plain_title": index_entry.get("plain_title") or "",
                "affected_place": index_entry.get("affected_place") or "",
                "source": "text",
                "match": match_type,
                "section_types": section_types,
                "row_count": len(index_entry["rows"]),
            }
            add_unique_list_item(
                resolution["budget_change_links"],
                resolution_link,
                ("budget_change_id", "opatreni_id", "source"),
            )

            opatreni = opatreni_by_id[opatreni_id]
            opatreni["resolution_links"].append({
                "resolution_id": resolution["id"],
                "relation": "mentions_budget_change",
                "budget_change_ids": [budget_change_id],
            })

            if resolution["id"] not in index_entry["resolution_ids"]:
                index_entry["resolution_ids"].append(resolution["id"])

        if mentions:
            stats["budget_change_links"] += len(mentions)

    # Merge same resolution/opatreni mention links into one item with many ids.
    for opatreni in linked_opatreni:
        merged = {}
        passthrough = []
        for link in opatreni["resolution_links"]:
            if link.get("relation") != "mentions_budget_change":
                passthrough.append(link)
                continue
            key = (link["resolution_id"], link["relation"])
            current = merged.setdefault(key, {
                "resolution_id": link["resolution_id"],
                "relation": "mentions_budget_change",
                "budget_change_ids": [],
            })
            current["budget_change_ids"].extend(link.get("budget_change_ids") or [])

        for link in merged.values():
            link["budget_change_ids"] = sorted(set(link["budget_change_ids"]), key=budget_change_sort_key)

        opatreni["resolution_links"] = passthrough + sorted(
            merged.values(),
            key=lambda item: item["resolution_id"],
        )

    for entry in budget_change_index.values():
        entry["resolution_ids"] = sorted(set(entry["resolution_ids"]))

    stats["resolutions_with_budget_change_links"] = sum(
        1 for resolution in linked_resolutions if resolution["budget_change_links"]
    )
    stats["opatreni_with_resolution_links"] = sum(
        1 for opatreni in linked_opatreni if opatreni["resolution_links"]
    )

    return linked_resolutions, linked_opatreni, budget_change_index, stats


def budget_change_sort_key(value: str):
    match = re.match(r"^(\d+)/(\d{4})/(RM|ZM)$", value)
    if not match:
        return (9999, 9999, value)
    number, year, organ = match.groups()
    return (int(year), organ, int(number))


def load_opatreni(input_dir: Path) -> list[dict]:
    return [
        load_json(path)
        for path in sorted(input_dir.glob("*.json"))
    ]


def write_outputs(output_dir: Path, resolutions: list[dict], opatreni_list: list[dict], budget_change_index: dict, stats: dict):
    output_dir.mkdir(parents=True, exist_ok=True)
    opatreni_output = output_dir / "rozpoctova-opatreni"
    opatreni_output.mkdir(parents=True, exist_ok=True)

    for stale in opatreni_output.glob("*.json"):
        stale.unlink()

    write_json(output_dir / "usneseni.json", resolutions)

    for opatreni in sorted(opatreni_list, key=lambda item: (item.get("year"), item.get("number"))):
        filename = opatreni["id"].replace("/", "-") + ".json"
        write_json(opatreni_output / filename, opatreni)

    sorted_index = {
        key: budget_change_index[key]
        for key in sorted(budget_change_index, key=budget_change_sort_key)
    }
    write_json(output_dir / "budget_change_index.json", sorted_index)
    write_json(output_dir / "stats.json", stats)


def main():
    ap = argparse.ArgumentParser(
        description="Propojí rozpočtová opatření s usneseními města Litovel"
    )
    ap.add_argument("--resolutions", type=Path, required=True, help="Cesta k phase3/usneseni.json")
    ap.add_argument("--opatreni", type=Path, required=True, help="Adresář JSON rozpočtových opatření")
    ap.add_argument("--output", type=Path, required=True, help="Výstupní adresář")
    args = ap.parse_args()

    resolutions = load_json(args.resolutions)
    opatreni_list = load_opatreni(args.opatreni)

    linked_resolutions, linked_opatreni, budget_change_index, stats = crosslink(
        resolutions,
        opatreni_list,
    )
    write_outputs(args.output, linked_resolutions, linked_opatreni, budget_change_index, stats)

    print("Propojení rozpočtových opatření hotovo ✔")
    print(f"Usnesení                 : {stats['total_resolutions']}")
    print(f"Rozpočtová opatření      : {stats['total_opatreni']}")
    print(f"Rozpočtové změny (RZ)    : {stats['budget_change_ids']}")
    print(f"Vazby RO → usnesení      : {stats['approval_links']}")
    print(f"Vazby usnesení → RZ      : {stats['budget_change_links']}")
    print(f"Opravené zdrojové odkazy : {len(stats['corrected_source_resolutions'])}")
    print(f"Nerozřešené zdrojové odkazy: {len(stats['unresolved_source_resolutions'])}")


if __name__ == "__main__":
    main()
