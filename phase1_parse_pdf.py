#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Parsování PDF s usneseními Rady nebo Zastupitelstva města Litovel.

Vstup:
  - jeden PDF soubor
  - NEBO složka s PDF soubory

Výstup:
  - jeden JSON soubor = jedno usnesení

Použití:
  python phase1_parse_pdf.py input.pdf output_dir/
  python phase1_parse_pdf.py pdf_dir/ output_dir/
"""

import pdfplumber
import argparse
import re
import json
import sys
import unicodedata
from pathlib import Path

from tools.usneseni_cz_pdf import is_usneseni_cz, parse_pages


# ---------- REGEXY ----------

USNESENI_SPLIT_RE = re.compile(
    r"\n(?=Číslo:\s+(?:RM|ZM)/\d+/\d+/\d+)"
)

ID_RE = re.compile(
    r"Číslo:\s+((?:RM|ZM)/\d+/\d+/\d+)"
)

DATE_RE = re.compile(
    r"(?:konané|ze)?\s*dne\s+(\d{1,2})\.\s*([^\s]+)\s*(\d{4})",
    re.IGNORECASE
)


# ---------- MAPA MĚSÍCŮ ----------

MONTHS = {
    "ledna": "01",
    "února": "02",
    "března": "03",
    "dubna": "04",
    "května": "05",
    "června": "06",
    "července": "07",
    "srpna": "08",
    "září": "09",
    "října": "10",
    "listopadu": "11",
    "prosince": "12",
}


# ---------- PDF → TEXT ----------

def pdf_to_text(path: Path) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n".join(pages)


# ---------- NORMALIZACE ----------

def normalize_text(text: str) -> str:
    text = re.sub(r"Stránka\s+\d+\s+z\s+\d+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def strip_rejected_proposals(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        folded = (
            unicodedata.normalize("NFKD", line)
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
            .strip()
        )
        if folded.startswith("navrhy, ktere nebyly prijaty"):
            return "\n".join(lines[:index]).strip()
    return text


# ---------- DATUM ----------

def parse_cz_date(text: str):
    m = DATE_RE.search(text)
    if not m:
        return None

    day, month_raw, year = m.groups()
    month_raw = month_raw.lower().strip(".")

    # číselný měsíc
    if month_raw.isdigit():
        month = month_raw.zfill(2)

    # slovní měsíc
    elif month_raw in MONTHS:
        month = MONTHS[month_raw]

    else:
        return None

    return f"{year}-{month}-{day.zfill(2)}"


# ---------- SPLIT USNESENÍ ----------

def split_usneseni(text: str):
    chunks = USNESENI_SPLIT_RE.split(text)
    return [c.strip() for c in chunks if c.strip()]


# ---------- PARSE JEDNOHO USNESENÍ ----------

def parse_usneseni(block: str, datum: str, organ: str, extra: dict | None = None):
    m = ID_RE.search(block)
    if not m:
        return None

    uid = m.group(1)
    body = block[m.end():].strip()

    record = {
        "id": uid,
        "datum": datum,
        "organ": organ,
        "text_raw": body
    }
    if extra:
        record.update(extra)
    return record


# ---------- ULOŽENÍ ----------

def save_usneseni(usn: dict, out_dir: Path):
    filename = usn["id"].replace("/", "-") + ".json"
    path = out_dir / filename

    with path.open("w", encoding="utf-8") as f:
        json.dump(usn, f, ensure_ascii=False, indent=2)


# ---------- ZPRACOVÁNÍ JEDNOHO PDF ----------

def detect_organ_from_id(text: str):
    m = ID_RE.search(text)
    if not m:
        return None, None

    prefix = m.group(1).split("/")[0]

    if prefix == "RM":
        return "Rada města Litovel", "RM"
    if prefix == "ZM":
        return "Zastupitelstvo města Litovel", "ZM"

    return None, None


def parse_text(text: str, extra: dict | None = None) -> tuple[list[dict], str | None]:
    clean_text = normalize_text(text)
    clean_text = strip_rejected_proposals(clean_text)

    datum = parse_cz_date(clean_text)
    if not datum:
        return [], "chybí datum"

    blocks = split_usneseni(clean_text)
    if not blocks:
        return [], "žádná usnesení"

    organ, prefix = detect_organ_from_id(clean_text)
    if not organ:
        return [], "neznámý orgán"

    usneseni = []
    for block in blocks:
        usn = parse_usneseni(block, datum, organ, extra)
        if usn:
            usneseni.append(usn)

    if not usneseni:
        return [], "žádná usnesení"
    return usneseni, None


def process_pdf(pdf_path: Path, out_dir: Path, failures: list):
    print(f"📄 {pdf_path}")

    usneseni, error = parse_pdf(pdf_path)
    if error:
        if error == "chybí datum":
            print("   ❌ nenalezeno datum")
        elif error == "žádná usnesení":
            print("   ❌ žádná usnesení")
        failures.append((pdf_path, error))
        return 0

    for usn in usneseni:
        save_usneseni(usn, out_dir)

    print(f"   → {len(usneseni)} usnesení ({usneseni[0]['datum']})")
    return len(usneseni)


def parse_pdf(path: Path, extra: dict | None = None) -> tuple[list[dict], str | None]:
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        if is_usneseni_cz(text):
            try:
                return parse_pages(pdf.pages, extra), None
            except ValueError as error:
                return [], f"Usnesení.cz: {error}"
        return parse_text(text, extra)

# ---------- MAIN ----------

def main():
    parser = argparse.ArgumentParser(description="Parsování PDF usnesení města Litovel")
    parser.add_argument("input", type=Path, help="PDF soubor nebo adresář s PDF")
    parser.add_argument("output", type=Path, help="Adresář pro JSON usnesení")
    parser.add_argument("--strict", action="store_true", help="Skončit chybou, pokud se některé PDF nepodaří zpracovat")
    args = parser.parse_args()
    input_path = args.input
    out_dir = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    failures = []

    total = 0

    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        total += process_pdf(input_path, out_dir, failures)

    elif input_path.is_dir():
        pdfs = sorted(input_path.glob("*.pdf"))
        if not pdfs:
            print("⚠️  Ve složce nejsou žádné PDF soubory")
            sys.exit(1)

        for pdf in pdfs:
            total += process_pdf(pdf, out_dir, failures)

    else:
        print("❌ Vstup musí být PDF soubor nebo složka s PDF")
        sys.exit(1)

    print(f"\n✅ Hotovo: celkem {total} usnesení")

    if failures:
        print("\n⚠️  SOUBORY, KTERÉ SE NEPODAŘILO ZPRACOVAT:")
        for path, reason in failures:
            print(f" - {path} ({reason})")
        if args.strict:
            sys.exit(1)
    else:
        print("\n🎉 Všechny PDF soubory zpracovány úspěšně")

if __name__ == "__main__":
    main()
