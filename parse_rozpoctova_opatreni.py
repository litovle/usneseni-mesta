#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Parsování PDF s rozpočtovými opatřeními města Litovel.

Vstup:
  - jeden PDF soubor
  - NEBO složka s PDF soubory

Výstup:
  - jeden JSON soubor = jedno rozpočtové opatření

Použití:
  python parse_rozpoctova_opatreni.py resources/rozpoctova-opatreni work/rozpoctova-opatreni
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pdfplumber

from tools.resolution_ids import RESOLUTION_ID_RE


HEADER_RE = re.compile(
    r"Rozpočtové opatření č\.\s*(?P<number>\d+)\s*/\s*(?P<year>\d{4})\s+"
    r"schválené\s+(?P<approved_by>Radou města Litovel|Zastupitelstvem města Litovel)",
    re.IGNORECASE,
)

APPROVAL_RE = re.compile(
    r"Rozpočtové opatření bylo schváleno na\s+"
    r"(?P<meeting_number>\d+)\.\s+(?P<meeting_type>schůzi|zasedání)\s+"
    r"(?P<approved_by>Rady města Litovel|Zastupitelstva města Litovel)\s+"
    r"dne\s+(?P<date>.+?)\s+na základě\s+usnesení\s+"
    r"(?P<resolutions>.+?)\.",
    re.IGNORECASE | re.DOTALL,
)

SECTION_RE = re.compile(
    r"^Změny\s+(?P<label>v příjmech|ve výdajích|ve financování):\s*$",
    re.IGNORECASE | re.MULTILINE,
)

BUDGET_CHANGE_RE = re.compile(
    r"\b(?:RZ\s+)?(?P<id>\d{1,4}\s*/\s*\d{4}\s*/\s*(?:RM|ZM))\b",
    re.IGNORECASE,
)

RESOLUTION_RE = re.compile(rf"\b{RESOLUTION_ID_RE.pattern}\b", re.IGNORECASE)

AMOUNT_RE = re.compile(r"(?<!\d)-?\d{1,3}(?:\s\d{3})*,\d{2}(?!\d)")
AMOUNT_CELL_RE = re.compile(r"^-?\d{1,3}(?:\s\d{3})*,\d{2}$")

NOTE_START_RE = re.compile(
    r"^(?:Rozpočtová změna č\.\s+(?P<long>.+)|RZ\s+(?P<short>\d{1,4}\s*/\s*\d{4}\s*/\s*(?:RM|ZM)))\s*$",
    re.IGNORECASE | re.MULTILINE,
)

MONTHS = {
    "ledna": "01",
    "února": "02",
    "unora": "02",
    "března": "03",
    "brezna": "03",
    "dubna": "04",
    "května": "05",
    "kvetna": "05",
    "června": "06",
    "cervna": "06",
    "července": "07",
    "cervence": "07",
    "srpna": "08",
    "září": "09",
    "zari": "09",
    "října": "10",
    "rijna": "10",
    "listopadu": "11",
    "prosince": "12",
}

SECTION_TYPES = {
    "v příjmech": "prijmy",
    "ve výdajích": "vydaje",
    "ve financování": "financovani",
}

TABLE_HEADER_WORDS = {
    "SU",
    "ODPA",
    "POL",
    "UZ",
    "PJ",
    "NÁSTROJ",
    "MU",
    "ORJ",
    "ORG",
    "Kč",
    "Popis",
}

TABLE_HEADER_PREFIX_RE = re.compile(
    r"^(?:§\s*)?(?:(?:SU|ODPA|POL|UZ|PJ|NÁSTROJ|MU|ORJ|ORG|Kč|Popis|§)\s+){2,}",
    re.IGNORECASE,
)

CHROME_FRAGMENT_RE = re.compile(
    r"(?:Město Litovel\s+)?IČO:?\s*\d[\d\s]*\s+ID datové schránky:\s*\S+\s+(?:e-?mail|email):\s*\S+"
    r"|(?:Město Litovel\s+)?ID datové schránky:\s*\S+\s+(?:e-?mail|email):\s*\S+\s+IČO:?\s*\d[\d\s]*"
    r"|č\.\s*účtu:\s*\S+\s+Tel\.:\s*\+?\d[\d\s]+\s+www\.\S+"
    r"|Tel\.:\s*\+?\d[\d\s]+\s+www\.\S+\s+č\.\s*účtu:\s*\S+"
    r"|Nám\.\s*Př\.\s*Otakara\s*778/1b"
    r"|784\s*01\s*Litovel",
    re.IGNORECASE,
)


def pdf_to_text(path: Path) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n".join(pages)


def pdf_pages_to_text(path: Path) -> list[str]:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_cz_date(value: str):
    value = " ".join(value.strip().strip(".").split())

    numeric = re.match(r"^(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})$", value)
    if numeric:
        day, month, year = numeric.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    textual = re.match(r"^(\d{1,2})\.\s*([^\s.]+)\s+(\d{4})$", value, re.IGNORECASE)
    if textual:
        day, month_raw, year = textual.groups()
        month = MONTHS.get(month_raw.lower().strip("."))
        if month:
            return f"{year}-{month}-{day.zfill(2)}"

    return None


def normalize_budget_change_id(value: str) -> str:
    return re.sub(r"\s+", "", value.upper())


def parse_amount(value: str) -> float:
    normalized = value.replace(" ", "").replace(",", ".")
    return float(normalized)


def find_amount_in_text(value: str):
    for line in value.splitlines():
        if "," not in line:
            continue

        amount = find_amount_in_line(line)
        if amount:
            return amount

    return None


def find_amount_in_line(line: str):
    prefix_match = re.search(r"(.+?)(,\d{2})", line)
    if not prefix_match:
        return None

    before_comma = prefix_match.group(1)
    decimal = prefix_match.group(2)

    if "-" in before_comma:
        m = re.search(r"-\d{1,3}(?:\s\d{3})*$", before_comma)
        if m:
            return m.group(0) + decimal

    groups = re.findall(r"\d{1,3}", before_comma)
    if not groups:
        return None

    for group_count in (3, 2, 1):
        if len(groups) < group_count:
            continue
        candidate_groups = groups[-group_count:]
        if group_count > 1 and candidate_groups[0].startswith("0"):
            continue
        candidate = " ".join(candidate_groups) + decimal
        value = parse_amount(candidate)
        # In this dataset, larger numeric groups before the amount are budget
        # codes, not part of the Kč value.
        if value <= 40_000_000:
            return candidate

    return groups[-1] + decimal


def text_without_repeated_chrome(text: str) -> str:
    """Remove repeated municipal PDF header/footer fragments from extracted text.

    Older PDFs often inject footer metadata in the middle of budget rows, and
    pdfplumber occasionally merges that footer with the following row label
    into a single line. Remove the chrome fragment but preserve any real row
    text that follows it on the same line.
    """
    lines = []
    for line in text.splitlines():
        stripped = CHROME_FRAGMENT_RE.sub(" ", line).strip()
        if not stripped:
            continue
        if stripped == "Město Litovel":
            continue
        lines.append(stripped)
    return "\n".join(lines)


def clean_description(text: str) -> str:
    text = text_without_repeated_chrome(text)
    text = TABLE_HEADER_PREFIX_RE.sub("", text).strip()
    text = re.sub(r"\bRZ\s+(\d+\s*/\s*\d{4}\s*/\s*(?:RM|ZM))", r"RZ \1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -)")


def extract_codes_and_description(chunk: str):
    amount = find_amount_in_text(chunk)
    if not amount:
        return [], clean_description(chunk), None, None

    amount_pos = chunk.find(amount)
    before = chunk[:amount_pos]
    after = chunk[amount_pos + len(amount):]

    before_lines = [line.strip() for line in before.splitlines() if line.strip()]
    code_line = ""
    description_lines = []

    for line in before_lines:
        tokens = line.split()
        if tokens and all(token.isdigit() for token in tokens):
            code_line = line
        elif not set(tokens).issubset(TABLE_HEADER_WORDS):
            description_lines.append(line)

    if not code_line and before_lines:
        last = before_lines[-1]
        if any(token.isdigit() for token in last.split()):
            code_line = last
            description_lines = before_lines[:-1]

    raw_codes = code_line.split() if code_line else []
    description = clean_description("\n".join(description_lines + [after]))
    return raw_codes, description, amount, parse_amount(amount)


def extract_sections(text: str):
    sections = []
    matches = list(SECTION_RE.finditer(text))

    for index, match in enumerate(matches):
        label = match.group("label").lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)

        note_match = NOTE_START_RE.search(text, start, end)
        if note_match:
            end = note_match.start()

        body = text[start:end].strip()
        rows = extract_rows(body)
        sections.append({
            "type": SECTION_TYPES[label],
            "label": match.group(0).strip().rstrip(":"),
            "rows": rows,
        })

    return sections


def extract_section_types(text: str) -> list[dict]:
    section_types = []
    for match in SECTION_RE.finditer(text):
        label = match.group("label").lower()
        section_types.append({
            "type": SECTION_TYPES[label],
            "label": match.group(0).strip().rstrip(":"),
        })
    return section_types


def clean_cell(value):
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
    return value or None


def is_table_header(cells: list[str]) -> bool:
    return "Kč" in cells and any(cell in TABLE_HEADER_WORDS for cell in cells)


def row_from_table_cells(cells: list[str]):
    amount_index = None
    for index, cell in enumerate(cells):
        if AMOUNT_CELL_RE.match(cell):
            amount_index = index
            break

    if amount_index is None:
        return None

    description = clean_description(" ".join(cells[amount_index + 1:]))
    budget_change_ids = [
        normalize_budget_change_id(match.group("id"))
        for match in BUDGET_CHANGE_RE.finditer(description)
    ]
    if not budget_change_ids:
        return None

    amount = cells[amount_index]
    return {
        "budget_change_id": budget_change_ids[0],
        "raw_codes": cells[:amount_index],
        "amount": amount,
        "amount_value": parse_amount(amount),
        "description": description,
    }


def extract_sections_from_tables(pdf_path: Path, text: str):
    section_types = extract_section_types(text)
    if not section_types:
        return []

    sections = []
    current_section = None
    next_section_index = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table:
                    continue

                first_cells = [cell for cell in (clean_cell(c) for c in table[0]) if cell]
                has_header = is_table_header(first_cells)

                if has_header:
                    if next_section_index < len(section_types):
                        current_section = {
                            **section_types[next_section_index],
                            "rows": [],
                        }
                        sections.append(current_section)
                        next_section_index += 1
                    rows = table[1:]
                else:
                    if current_section is None:
                        if next_section_index >= len(section_types):
                            continue
                        current_section = {
                            **section_types[next_section_index],
                            "rows": [],
                        }
                        sections.append(current_section)
                        next_section_index += 1
                    rows = table

                for raw_row in rows:
                    cells = [cell for cell in (clean_cell(c) for c in raw_row) if cell]
                    if not cells or is_table_header(cells):
                        continue

                    row = row_from_table_cells(cells)
                    if row:
                        current_section["rows"].append(row)

    return sections


def extract_rows(section_text: str):
    rows = []
    matches = list(BUDGET_CHANGE_RE.finditer(section_text))

    for index, match in enumerate(matches):
        chunk_end = match.end()
        prev_end = matches[index - 1].end() if index else 0
        chunk = section_text[prev_end:chunk_end]

        raw_codes, description, amount, amount_value = extract_codes_and_description(chunk)
        if not amount or not AMOUNT_CELL_RE.match(amount):
            continue

        budget_change_id = normalize_budget_change_id(match.group("id"))

        rows.append({
            "budget_change_id": budget_change_id,
            "raw_codes": raw_codes,
            "amount": amount,
            "amount_value": amount_value,
            "description": description,
        })

    return rows


def merge_fallback_sections(primary: list[dict], fallback: list[dict]) -> list[dict]:
    if not primary:
        return fallback

    primary_by_type = {}
    seen_rows = set()
    seen_descriptions = set()
    for section in primary:
        primary_by_type.setdefault(section["type"], section)
        for row in section["rows"]:
            seen_rows.add(row_key(section["type"], row))
            seen_descriptions.add(row_description_key(section["type"], row))

    for fallback_section in fallback:
        target = primary_by_type.get(fallback_section["type"])
        if target is None:
            primary.append(fallback_section)
            primary_by_type[fallback_section["type"]] = fallback_section
            for row in fallback_section["rows"]:
                seen_rows.add(row_key(fallback_section["type"], row))
                seen_descriptions.add(row_description_key(fallback_section["type"], row))
            continue

        for row in fallback_section["rows"]:
            key = row_key(fallback_section["type"], row)
            description_key = row_description_key(fallback_section["type"], row)
            if key in seen_rows or description_key in seen_descriptions:
                continue
            target["rows"].append(row)
            seen_rows.add(key)
            seen_descriptions.add(description_key)

    return normalize_financing_sections(primary)


def normalize_financing_sections(sections: list[dict]) -> list[dict]:
    """
    Some RO PDFs repeat the expenditure heading before financing rows.
    Budget financing rows use položka 8xxx (for example 8115), so relabel
    those sections for a clearer public export.
    """
    for section in sections:
        if section.get("type") != "vydaje":
            continue

        rows = section.get("rows") or []
        if not rows:
            continue

        first_codes = [
            (row.get("raw_codes") or [""])[0]
            for row in rows
            if row.get("raw_codes")
        ]
        if first_codes and all(code.startswith("8") for code in first_codes):
            section["type"] = "financovani"
            section["label"] = "Změny ve financování"

    return sections


def row_key(section_type: str, row: dict):
    return (
        section_type,
        row.get("budget_change_id"),
        row.get("amount"),
    )


def row_description_key(section_type: str, row: dict):
    description = row.get("description") or ""
    budget_change_id = row.get("budget_change_id") or ""

    description = re.sub(
        r"\(?\s*RZ\s+" + re.escape(budget_change_id) + r"\)?",
        "",
        description,
        flags=re.IGNORECASE,
    )
    description = re.sub(r"\s+", " ", description).strip(" .;-").lower()

    return (
        section_type,
        budget_change_id,
        description,
    )


def extract_notes(text: str):
    """Extract official explanatory notes for each RZ.

    Newer PDFs label notes as `Rozpočtová změna č. 53/2026/RM`, while older
    exports use the shorter standalone heading `RZ 13/2022/RM`. Support both
    forms so official notes remain available for rendering across all years.
    """
    notes = []
    matches = list(NOTE_START_RE.finditer(text))
    if not matches:
        return notes

    terminal_markers = [
        "\nVe Zveřejněném rozpočtovém opatření",
        "\nDo listinné podoby",
        "\nZpracovala:",
    ]

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        for marker in terminal_markers:
            marker_pos = text.find(marker, start, end)
            if marker_pos != -1:
                end = min(end, marker_pos)

        note_id = match.group("long") or match.group("short") or ""
        notes.append({
            "title": "Rozpočtová změna č. " + " ".join(note_id.split()),
            "text": clean_description(text[start:end]),
        })

    return notes


def sanitize_parsed_content(sections: list[dict], notes: list[dict]) -> tuple[list[dict], list[dict]]:
    """Apply the same description cleanup across all parser branches.

    Table-based extraction and text fallback do not always produce identical
    intermediate strings. Run one final normalization pass so footer/header
    fragments are removed consistently from row descriptions and note text.
    """
    for section in sections:
        for row in section.get("rows") or []:
            row["description"] = clean_description(row.get("description") or "")

    for note in notes:
        note["text"] = clean_description(note.get("text") or "")

    return sections, notes


def parse_opatreni(pdf_path: Path):
    text = normalize_text(pdf_to_text(pdf_path))

    header = HEADER_RE.search(text)
    if not header:
        raise ValueError("nenalezeno záhlaví rozpočtového opatření")

    number = int(header.group("number"))
    year = int(header.group("year"))
    approved_by = header.group("approved_by")
    organ = "RM" if approved_by.startswith("Radou") else "ZM"

    date_match = re.search(r"\bdne\s+([^\n]+)", text[header.end():], re.IGNORECASE)
    approval_date_raw = date_match.group(1).strip() if date_match else None
    approval_date = parse_cz_date(approval_date_raw) if approval_date_raw else None

    approval = APPROVAL_RE.search(text)
    meeting = None
    source_resolutions = []
    if approval:
        meeting = {
            "number": int(approval.group("meeting_number")),
            "type": approval.group("meeting_type").lower(),
            "date": parse_cz_date(approval.group("date")) or approval.group("date").strip(),
        }
        source_resolutions = RESOLUTION_RE.findall(approval.group("resolutions"))

    table_sections = extract_sections_from_tables(pdf_path, text)
    fallback_sections = extract_sections(text)
    sections = merge_fallback_sections(table_sections, fallback_sections)
    notes = extract_notes(text)
    sections, notes = sanitize_parsed_content(sections, notes)
    budget_change_ids = sorted({
        row["budget_change_id"]
        for section in sections
        for row in section["rows"]
    })

    return {
        "id": f"RO/{number}/{year}",
        "number": number,
        "year": year,
        "approval_date": approval_date,
        "approved_by": approved_by,
        "organ": organ,
        "meeting": meeting,
        "source_resolutions": source_resolutions,
        "budget_change_ids": budget_change_ids,
        "sections": sections,
        "notes": notes,
        "source_pdf": str(pdf_path),
        "text_raw": text,
    }


def save_opatreni(opatreni: dict, out_dir: Path):
    filename = opatreni["id"].replace("/", "-") + ".json"
    path = out_dir / filename
    path.write_text(
        json.dumps(opatreni, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def iter_pdfs(input_path: Path):
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.glob("*.pdf"))
    return []


def main():
    ap = argparse.ArgumentParser(
        description="Parser rozpočtových opatření města Litovel"
    )
    ap.add_argument("input", type=Path, help="PDF soubor nebo adresář s PDF")
    ap.add_argument("output", type=Path, help="Výstupní adresář pro JSON")
    args = ap.parse_args()

    pdfs = iter_pdfs(args.input)
    if not pdfs:
        print(f"❌ Nenalezeny žádné PDF soubory: {args.input}", file=sys.stderr)
        sys.exit(1)

    args.output.mkdir(parents=True, exist_ok=True)

    failures = []
    total_rows = 0
    for pdf_path in pdfs:
        try:
            opatreni = parse_opatreni(pdf_path)
        except Exception as exc:
            failures.append((pdf_path, str(exc)))
            print(f"❌ {pdf_path}: {exc}")
            continue

        save_opatreni(opatreni, args.output)
        row_count = sum(len(section["rows"]) for section in opatreni["sections"])
        total_rows += row_count
        print(f"📄 {pdf_path} → {opatreni['id']} ({row_count} řádků)")

    print(f"\n✅ Hotovo: {len(pdfs) - len(failures)} opatření, {total_rows} řádků")

    if failures:
        print("\n⚠️  SOUBORY, KTERÉ SE NEPODAŘILO ZPRACOVAT:")
        for path, reason in failures:
            print(f" - {path} ({reason})")
        sys.exit(1)


if __name__ == "__main__":
    main()
