#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Vytvoří index pro fulltextové vyhledávání rozpočtových opatření.

Vstup:
  - adresář s propojenými JSON soubory rozpočtových opatření

Výstup:
  - index adresář s indexy pro vyhledávání. Jeden JSON soubor = jeden obsahový rok.
  - data adresář s rozpočtovými opatřeními. Jeden JSON soubor = jeden obsahový rok.
  - meta.json se statistickými metadaty, například počty opatření za jednotlivé roky

Použití:
  python phase4_ro_index_build.py --input work/rozpoctova-opatreni-linked/rozpoctova-opatreni --output work/phase4/ro
"""

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from tools.search_index_format import write_compact_index


WORD_RE = re.compile(r"[a-z0-9]{3,}")


def normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def opatreni_content_year(opatreni: dict) -> str:
    year = opatreni.get("year")
    if year is not None:
        return str(year)

    oid = opatreni.get("id", "")
    parts = oid.split("/")
    if len(parts) >= 3 and parts[-1]:
        return parts[-1]

    return ""


def extract_text(opatreni: dict) -> str:
    parts = []

    for key in ("id", "approved_by", "approval_date", "organ"):
        value = opatreni.get(key)
        if value:
            parts.append(str(value))

    meeting = opatreni.get("meeting") or {}
    for key in ("number", "type", "date"):
        value = meeting.get(key)
        if value:
            parts.append(str(value))

    for value in opatreni.get("source_resolutions", []):
        parts.append(str(value))

    for value in opatreni.get("budget_change_ids", []):
        parts.append(str(value))

    for note in opatreni.get("notes", []):
        if note.get("title"):
            parts.append(str(note["title"]))
        if note.get("text"):
            parts.append(str(note["text"]))

    for section in opatreni.get("sections", []):
        if section.get("label"):
            parts.append(str(section["label"]))
        if section.get("type"):
            parts.append(str(section["type"]))

        for row in section.get("rows", []):
            for value in row.get("raw_codes", []):
                parts.append(str(value))
            for key in ("budget_change_id", "amount", "description"):
                value = row.get(key)
                if value:
                    parts.append(str(value))

    return " ".join(parts)


def build_index(opatreni_list: list[dict]) -> dict:
    index = defaultdict(set)

    for opatreni in opatreni_list:
        oid = opatreni["id"]
        text = normalize(extract_text(opatreni))

        for token in WORD_RE.findall(text):
            index[token].add(oid)

            for i in range(4, len(token)):
                index[token[:i]].add(oid)

    return {key: sorted(value) for key, value in index.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", type=Path, required=True)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit("Input directory does not exist.")

    all_data = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(args.input.glob("*.json"))
    ]

    by_year = defaultdict(list)
    meta = {}

    for opatreni in all_data:
        year = opatreni_content_year(opatreni)
        if not year:
            continue
        by_year[year].append(opatreni)

    (args.output / "index").mkdir(parents=True, exist_ok=True)
    (args.output / "data").mkdir(parents=True, exist_ok=True)

    for year, items in sorted(by_year.items()):
        index = build_index(items)

        write_compact_index(args.output / "index" / f"{year}.json", index)

        (args.output / "data" / f"{year}.json").write_text(
            json.dumps(items, ensure_ascii=False),
            encoding="utf-8",
        )

        meta[year] = {
            "count": len(items),
        }

    (args.output / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("FÁZE 4 RO hotová ✔")
    print("Roky:", ", ".join(sorted(meta.keys())))


if __name__ == "__main__":
    main()
