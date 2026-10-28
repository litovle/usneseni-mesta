#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Analýza a tematická klasifikace usnesení (Enrich v pipeline.py).

Samostatný běh bez --classifier-url provede strukturální analýzu.
Pipeline předává URL finálního modelového balíčku, jeho SHA-256 a cestu k cache;
pak se do každého výstupu přidá classification s kategorií, zdrojem, stavem,
URL a SHA-256 modelového archivu a skóre modelu na dvě desetinná místa. Kategorie pochází
přímo z modelu, bez ručních oprav nebo předem určených příznaků pro kontrolu.
Inference používá stažené lokální váhy a nepotřebuje repozitář klasifikátoru.

Zpracuje JSON z phase 1

{
  "id": "RM/1/1/2022",
  "datum": "2022-10-27",
  "organ": "Rada města Litovel",
  "text_raw": "text_usneseni"
}

na

{
  "id": "RM/1/1/2022",
  "datum": "2022-10-27",
  "organ": "Rada města Litovel",
  "actions": [
    "schvaluje",
    "souhlasí"
  ],
  "subject": null,
  "items": [
    {
      "label": "a",
      "text": "text_1"  
    },
    {
      "label": "b",
      "text": "text_2"    
    }
  ],
  "tail": null,
  "references_out": [],
  "amounts": [
    "10.000 Kč"
  ]
}

  - jsou extrahovány akce
  - z usnesení s více body jsou jednotlivé akce extrahovány a body rozděleny
  - odděleny jsou subject a tail (text před a za body) pokud jsou přítomny
  - jsou extrahovány peněžní částky
  - jsou hrubě extrahovány reference (resolvuje je další operace v Enrich)
  - při zadání --classifier-url se přidá tematická klasifikace

Vstup:
  - adresář s JSON soubory ve výše definované struktuře z phase 1

Výstup:
  - jeden JSON soubor = jedno usnesení

Použití:
  python phase2_resolution_analysis.py --input work/phase1 --output work/phase3
  python phase2_resolution_analysis.py --input work/phase1 --output work/phase3 \
    --classifier-url MODEL_URL --classifier-sha256 SHA256

Predikce a fronta pro kontrolu se zapisují do --classification-output (výchozí:
classifier/ vedle výstupního adresáře). --classifier-cache určuje cache modelu.
"""

import json
import re
import argparse
from pathlib import Path
from collections import Counter


# ============================================================
# REGEXY
# ============================================================

ID_RE = re.compile(r"^(RM|ZM)/\d+/\d+/\d+$")
ITEM_RE = re.compile(r"(?:^|\n)([a-z])\)\s+")

ACTION_PHRASES = [
    "uděluje předběžný souhlas",
    "uděluje výjimku",
    "byla seznámena",
    "bere na vědomí",
    "schvaluje",
    "souhlasí",
    "ukládá",
    "revokuje",
    "vydává",
    "stanovuje",
    "doporučuje",
    "odkládá",
    "jmenuje",
    "pověřuje",
    "svěřuje",
    "určuje",
    "zajistí",
    "vyhovuje",
    "rozhoduje",
    "rozhodla",
    "projednala",
    "konstatuje",
    "potvrzuje",
    "navrhuje",
    "nominuje",
    "volí",
    "stahuje bod",
    "zřizuje",
    "deleguje",
    "poskytuje",
    "se zavazuje",
    "přijímá dotaci"
]

ORG_HEADERS = [
    "Rada města Litovel",
    "Zastupitelstvo města Litovel",
]

ACTION_RE = re.compile(
    r"^(ne)?(" + "|".join(map(re.escape, ACTION_PHRASES)) + r")\b",
    re.IGNORECASE
)

ACTION_NORMALIZATION = {
    "rozhodla": "rozhoduje",
    "byla seznámena": "bere na vědomí",
    "projednala": "projednává",
}

REF_EXPLICIT_RE = re.compile(r"\b(?:RM|ZM)/\d+/\d+/\d+\b")
REF_IMPLICIT_RE = re.compile(r"\b\d{1,4}/\d{1,3}\b")
AMOUNT_RE = re.compile(r"\b\d{1,3}(?:[ .]\d{3})*\s*Kč\b")

#Najdi konec řádku (\n), po kterém NÁSLEDUJE slovo začínající malým písmenem.
TAIL_LINE_RE = re.compile(r"\n(?=[a-záčďéěíňóřšťúůýž])")
CORE_RAW_KEYS = {"id", "datum", "organ", "text_raw"}


# ============================================================
# HELPERY
# ============================================================

def normalize_action(a):
    if not a:
        return None
    return ACTION_NORMALIZATION.get(a.lower(), a.lower())


def normalize_amount_text(text):
    """
    Spojí rozdělené částky typu:
    '2.\n000 Kč' → '2.000 Kč'
    """
    # spojení čísla + tečky + zalomení + čísla
    text = re.sub(r"(\d)\.\s*\n\s*(\d{3})\s*Kč", r"\1.\2 Kč", text)

    # případ bez tečky: '2\n000 Kč'
    text = re.sub(r"(\d)\s*\n\s*(\d{3})\s*Kč", r"\1\2 Kč", text)

    return text


def split_header(text):
    text = text.lstrip()
    for h in ORG_HEADERS:
        if text.startswith(h):
            return h, text[len(h):].lstrip(" ,\n")
    return None, text


def split_head_items(text):
    m = ITEM_RE.search(text)
    if not m:
        return text.strip(), []

    head = text[:m.start()].strip()
    rest = text[m.start():]

    items = []
    matches = list(ITEM_RE.finditer(rest))
    for i, im in enumerate(matches):
        start = im.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(rest)
        items.append({
            "label": im.group(1),
            "text": rest[start:end].strip()
        })

    return head, items


def extract_action(text):
    if not text:
        return None

    norm = text.lstrip("\ufeff \t\n\r\xa0").lower()
    m = ACTION_RE.match(norm)
    if not m:
        return None

    neg = m.group(1)
    base = m.group(2)

    if neg:
        return "ne" + base
    return base


def extract_action_and_subject(head):
    h = head.strip()

    for org in ORG_HEADERS:
        if h.lower().startswith(org.lower()):
            h = h[len(org):].lstrip(" ,")

    action = extract_action(h)
    if not action:
        return None, h.rstrip(":") or None

    subject = h[len(action):].strip().lstrip(",").rstrip(":") or None
    return action, subject


def extract_refs(text):
    refs = []

    # explicitní reference
    for m in REF_EXPLICIT_RE.findall(text):
        refs.append({
            "raw": m,
            "type": "explicit",
            "resolved": m
        })

    # implicitní reference – pouze v kontextu "usnesení / usn."
    for m in re.finditer(r"(usnesení|usn\.)\s*(č\.?)?\s*(\d{1,4}/\d{1,3})", text, re.IGNORECASE):
        refs.append({
            "raw": m.group(3),
            "type": "implicit",
            "resolved": None
        })

    return refs


def extract_amounts(text):
    return sorted(set(AMOUNT_RE.findall(text)))


def split_tail_from_last_item(items):
    if not items:
        return items, None

    last = items[-1]
    txt = last["text"]

    m = TAIL_LINE_RE.search(txt)
    if not m:
        return items, None

    head = txt[:m.start()].strip()
    tail = txt[m.start():].strip()

    # bezpečnostní brzda
    if len(head.split()) < 3:
        return items, None

    last["text"] = head
    return items, tail

def dedupe_refs(refs):
    seen = {}
    for r in refs:
        seen[r["raw"]] = r
    return list(seen.values())


def provenance_fields(raw):
    return {
        key: value
        for key, value in raw.items()
        if key not in CORE_RAW_KEYS
    }

# ============================================================
# CORE
# ============================================================

def process_usneseni(raw):
    organ, body = split_header(raw["text_raw"])
    head, items = split_head_items(body)

    # zjisti, zda položky nesou vlastní rozhodnutí
    item_actions = [extract_action(it["text"]) for it in items]
    has_local_actions = any(item_actions)

    refs = []
    amounts = set()
    actions = set()

    # ========================================================
    # TYP B: sekvence rozhodnutí (a) revokuje, b) schvaluje…
    # ========================================================
    if has_local_actions:
        for it, act in zip(items, item_actions):
            if act:
                actions.add(act)

            refs.extend(extract_refs(it["text"]))
            norm = normalize_amount_text(it["text"])
            amounts.update(extract_amounts(norm))

        parsed = {
            "id": raw["id"],
            "datum": raw.get("datum"),
            "organ": organ,
            "actions": sorted(actions),
            "subject": None,
            "items": items,
            "tail": None,
            "references_out": dedupe_refs(refs),
            "amounts": sorted(amounts)
        }
        parsed.update(provenance_fields(raw))
        return parsed

    # ========================================================
    # TYP A: globální akce + výčet předmětu
    # ========================================================
    action, subject = extract_action_and_subject(head)
    if action:
        actions.add(action)

    if subject:
        norm = normalize_amount_text(subject)
        amounts.update(extract_amounts(norm))

    items, tail = split_tail_from_last_item(items)

    for it in items:
        refs.extend(extract_refs(it["text"]))
        norm = normalize_amount_text(it["text"])
        amounts.update(extract_amounts(norm))
    if tail:
        refs.extend(extract_refs(tail))
        norm = normalize_amount_text(tail)
        amounts.update(extract_amounts(norm))
    parsed = {
        "id": raw["id"],
        "datum": raw.get("datum"),
        "organ": organ,
        "actions": sorted(actions),
        "subject": subject,
        "items": items,
        "tail": tail,
        "references_out": dedupe_refs(refs),
        "amounts": sorted(amounts)
    }
    parsed.update(provenance_fields(raw))
    return parsed


# ============================================================
# MAIN
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", type=Path, required=True)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--classifier-url", help="URL finálního tematického modelového balíčku.")
    ap.add_argument("--classifier-sha256", help="Očekávaný SHA-256 modelového balíčku.")
    ap.add_argument("--classifier-cache", type=Path, default=Path(".cache/resolution-classifier"))
    ap.add_argument("--classification-output", type=Path, help="Adresář predikcí a fronty pro kontrolu.")
    ap.add_argument("--incremental-classification", action="store_true",
                    help="Znovu použít platné klasifikace z existujících výstupů.")
    args = ap.parse_args()

    classifications = {}
    if args.classifier_url:
        from resolution_classification import DEFAULT_SHA256
        from resolution_classification.runner import classify_records

        records = {}
        previous = {}
        for p in sorted(args.input.glob("*.json")):
            raw = json.loads(p.read_text(encoding="utf-8"))
            if raw["id"] in records:
                ap.error(f"Duplicitní ID usnesení: {raw['id']}")
            records[raw["id"]] = raw
            if args.incremental_classification:
                old = args.output / p.name
                if old.is_file():
                    try:
                        saved = json.loads(old.read_text(encoding="utf-8"))
                        if saved.get("id") == raw["id"]:
                            previous[raw["id"]] = saved.get("classification")
                    except (ValueError, OSError, AttributeError):
                        pass
        classifications = classify_records(
            records, args.input,
            args.classification_output or args.output.parent / "classifier",
            args.classifier_url, args.classifier_sha256 or DEFAULT_SHA256, args.classifier_cache,
            **({"previous": previous} if args.incremental_classification else {}),
        )

    args.output.mkdir(parents=True, exist_ok=True)

    stats = Counter()
    action_counter = Counter()

    for p in sorted(args.input.glob("*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))

        if not ID_RE.match(raw.get("id", "")):
            if args.verbose:
                print(f"⚠️  Neplatné ID: {p.name}")
            continue

        parsed = process_usneseni(raw)
        if args.classifier_url:
            parsed["classification"] = classifications[raw["id"]]
        stats["total"] += 1

        for a in parsed["actions"]:
            action_counter[a] += 1

        if not parsed["actions"]:
            stats["missing_action"] += 1

        (args.output / p.name).write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    print("\n=== STATISTIKY ===")
    for k, v in stats.items():
        print(f"{k:20}: {v}")

    print("\n=== AKCE ===")
    for a, c in action_counter.most_common():
        print(f"{a:20}: {c}")

    print("\nHotovo ✔")


if __name__ == "__main__":
    main()
