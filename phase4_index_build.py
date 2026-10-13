#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Export: vytvoří index usnesení a roční JSON z finálních obohacených dat.

Vstup:
  - usneseni.json s klasifikací, referencemi a při plném běhu i rozpočtovými vazbami

Výstup:
  - index adresář s indexy pro vyhledávání. Jeden JSON soubor = jeden rok.
  - data adresář s usneseními. Jeden JSON soubor = jeden rok.
  - meta.json se statistickými metadaty, například počty rozhodnutí za jednotlivé roky

Použití:
  python phase4_index_build.py --input work/rozpoctova-opatreni-linked/usneseni.json --output export/assets/usneseni
"""

import json
import argparse
import unicodedata
import re
from pathlib import Path
from collections import defaultdict


WORD_RE = re.compile(r"[a-z0-9]{3,}")


def normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def extract_text(u: dict) -> str:
    parts = []

    if u.get("subject"):
        parts.append(u["subject"])

    for it in u.get("items", []):
        parts.append(it["text"])

    for a in u.get("actions", []):
        parts.append(a)

    for am in u.get("amounts", []):
        parts.append(am)

    parts.append(u["id"])
    return " ".join(parts)


def build_index(usneseni: list) -> dict:
    index = defaultdict(set)

    for u in usneseni:
        uid = u["id"]
        text = normalize(extract_text(u))

        for w in WORD_RE.findall(text):
            # celý token
            index[w].add(uid)

            # prefixy (min. délka 4)
            for i in range(4, len(w)):
                index[w[:i]].add(uid)

    return {k: sorted(v) for k, v in index.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", type=Path, required=True)   # phase3/usneseni.json
    ap.add_argument("-o", "--output", type=Path, required=True)  # litovle.cz/assets/usneseni
    args = ap.parse_args()

    all_data = json.loads(args.input.read_text(encoding="utf-8"))

    by_year = defaultdict(list)
    meta = {}

    for u in all_data:
        year = u["id"].split("/")[-1]
        by_year[year].append(u)

    (args.output / "index").mkdir(parents=True, exist_ok=True)
    (args.output / "data").mkdir(parents=True, exist_ok=True)

    for year, items in sorted(by_year.items()):
        index = build_index(items)

        (args.output / "index" / f"{year}.json").write_text(
            json.dumps(index, ensure_ascii=False),
            encoding="utf-8"
        )

        (args.output / "data" / f"{year}.json").write_text(
            json.dumps(items, ensure_ascii=False),
            encoding="utf-8"
        )

        meta[year] = {
            "count": len(items)
        }

    (args.output / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("FÁZE 4 hotová ✔")
    print("Roky:", ", ".join(sorted(meta.keys())))


if __name__ == "__main__":
    main()
