#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enrich: resolvování referencí a volebních období.

Usnesení mohou odkazovat jedno na druhé. V této fázi se resolvují reference
  - imlicitní: Uváděné v textu rozhodnutí pouze jako ID_ROZHODNUTI/CISLO_SCHUZE, například 1853/60 je resolvováno na RM/1853/60/2025
  - explicitní: Už hotová reference ve tvaru RM/1853/60/2025

Resolvované reference se vloží do nového klíče references_in a odkaz je tak oboustranný.

Na závěr jsou do konzole vytištěné statistiky.

Vstup:
  - adresář s analyzovanými usneseními, včetně classification

Výstup:
  - usneseni.json se všemi usneseními; classification se zachovává

Použití:
  python phase3_resolve_references.py --input work/phase3 --output work/phase4
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict, Counter
import re

from election_terms import apply_term_metadata, load_terms


ID_RE = re.compile(r"^(RM|ZM)/(\d+)/(\d+)/(\d+)$")

def parse_id(id_str):
    """
    RM/1962/65/2025 -> (RM, 1962, 65, 2025)
    """
    m = ID_RE.match(id_str)
    if not m:
        return None

    org, num, schuze, rok = m.groups()
    return org, int(num), int(schuze), int(rok)


def resolution_sort_key(record):
    parsed = parse_id(record.get("id", ""))
    if not parsed:
        return ("", "", 0, "")
    _org, _num, _meeting, year = parsed
    return (record.get("datum") or f"{year}-12-31", record.get("id") or "")


def source_allows_candidate(source, candidate):
    source_date = source.get("datum")
    candidate_date = candidate.get("datum")
    if source_date and candidate_date:
        return candidate_date <= source_date

    source_parsed = parse_id(source.get("id", ""))
    candidate_parsed = parse_id(candidate.get("id", ""))
    if not source_parsed or not candidate_parsed:
        return False
    return candidate_parsed[3] <= source_parsed[3]


def resolve_implicit_reference(raw, source, by_key):
    source_parsed = parse_id(source.get("id", ""))
    if not source_parsed:
        return None, "invalid_source"
    source_org, _source_num, _source_meeting, _source_year = source_parsed

    try:
        num, schuze = map(int, raw.split("/"))
    except ValueError:
        return None, "invalid_raw"

    candidates = [
        candidate
        for candidate in by_key.get((source_org, num, schuze), [])
        if source_allows_candidate(source, candidate)
    ]
    if not candidates:
        return None, "no_candidate"

    candidates = sorted(candidates, key=resolution_sort_key)
    latest_key = resolution_sort_key(candidates[-1])
    latest = [candidate for candidate in candidates if resolution_sort_key(candidate) == latest_key]
    if len(latest) > 1:
        return None, "ambiguous"
    return latest[0]["id"], None


def build_resolution_indexes(usneseni):
    by_key = defaultdict(list)  # (org, num, schuze) -> [resolution]
    for data in usneseni:
        parsed = parse_id(data.get("id", ""))
        if not parsed:
            continue
        org, num, schuze, _rok = parsed
        by_key[(org, num, schuze)].append(data)

    for key in by_key:
        by_key[key].sort(key=resolution_sort_key)
    return by_key


def process_resolutions(usneseni, terms=None):
    for data in usneseni:
        apply_term_metadata(data, terms)

    by_key = build_resolution_indexes(usneseni)

    refs_index = {}
    unresolved = []
    ambiguous = []
    resolved_count = 0

    for u in usneseni:
        uid = u["id"]
        u["references_in"] = []

        if not parse_id(uid):
            continue

        for r in u.get("references_out", []):
            raw = r["raw"]

            # explicitní reference už je hotová
            if r["type"] == "explicit":
                r["resolved"] = raw
                refs_index[(uid, raw)] = raw
                resolved_count += 1
                continue

            chosen, reason = resolve_implicit_reference(raw, u, by_key)
            if chosen:
                r["resolved"] = chosen
                refs_index[(uid, raw)] = chosen
                resolved_count += 1
            elif reason == "ambiguous":
                ambiguous.append((uid, raw))
            else:
                unresolved.append((uid, raw))

    by_id = {u["id"]: u for u in usneseni}

    for u in usneseni:
        src = u["id"]
        for r in u.get("references_out", []):
            tgt = r.get("resolved")
            if not tgt:
                continue
            if tgt not in by_id:
                continue

            by_id[tgt]["references_in"].append({
                "from": src,
                "action": next(iter(u["actions"]), None)
            })

    stats = {
        "total_usneseni": len(usneseni),
        "refs_total": sum(len(u.get("references_out", [])) for u in usneseni),
        "refs_resolved": resolved_count,
        "refs_unresolved": len(unresolved),
        "refs_ambiguous": len(ambiguous),
        "unresolved_refs": unresolved,
        "ambiguous_refs": ambiguous,
    }
    return usneseni, refs_index, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", type=Path, required=True)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--terms", type=Path, help="Volitelný JSON se seznamem volebních období.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # ======================================================
    # 1️⃣ Načtení všech usnesení
    # ======================================================

    usneseni = []
    for p in sorted(args.input.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue

        resolution_id = data.get("id")
        if not resolution_id:
            continue

        parsed = parse_id(resolution_id)
        if not parsed:
            continue

        usneseni.append(data)

    if args.verbose:
        print(f"Načteno usnesení: {len(usneseni)}")

    terms = load_terms(args.terms)
    usneseni, refs_index, stats = process_resolutions(usneseni, terms)

    # ======================================================
    # 5️⃣ Výstupy
    # ======================================================

    (args.output / "usneseni.json").write_text(
        json.dumps(usneseni, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    (args.output / "refs_index.json").write_text(
        json.dumps(
            {f"{k[0]} -> {k[1]}": v for k, v in refs_index.items()},
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    (args.output / "stats_refs.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("FÁZE 3 hotová ✔")
    print(f"Usnesení       : {stats['total_usneseni']}")
    print(f"Reference celkem: {stats['refs_total']}")
    print(f"Rozřešeno       : {stats['refs_resolved']}")
    print(f"Nerozřešeno     : {stats['refs_unresolved']}")
    print(f"Nejednoznačné   : {stats['refs_ambiguous']}")


if __name__ == "__main__":
    main()
