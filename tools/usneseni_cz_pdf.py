"""Read the adopted-resolution tables exported by Usneseni.cz."""

import re
import unicodedata
from datetime import date

try:
    from resolution_ids import USNESENI_CZ_ID_RE as SOURCE_ID_RE, require_resolution_id
except ImportError:
    from tools.resolution_ids import USNESENI_CZ_ID_RE as SOURCE_ID_RE, require_resolution_id

ORGANS = {"R": "Rada města Litovel", "Z": "Zastupitelstvo města Litovel"}
HEADERS = {"číslo usnesení": "id", "text usnesení": "text", "datum jednání": "date"}
BODY_RE = re.compile(r"Text\s+přijatého\s+usnesení\s*:\s*", re.IGNORECASE)


def is_usneseni_cz(text: str) -> bool:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    folded = " ".join(folded.split())
    return bool(SOURCE_ID_RE.search(text)) and all(
        label in folded for label in ("text usneseni", "datum", "hlasovani")
    )


def cell_text(value: str | None) -> str:
    return " ".join((value or "").split())


def parse_meeting_date(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", cell_text(value))
    if not match:
        raise ValueError(f"Neplatné datum jednání: {value!r}")
    day, month, year = map(int, match.groups())
    return date(year, month, day).isoformat()


def parse_tables(tables, extra: dict | None = None) -> list[dict]:
    """Keep decision text separate from the other columns, including page continuations."""
    rows = []
    seen = set()
    for table in tables:
        if not table:
            continue
        columns = {HEADERS[cell_text(label).lower()]: position
                   for position, label in enumerate(table[0])
                   if cell_text(label).lower() in HEADERS}
        if set(columns) != {"id", "text", "date"}:
            if any(SOURCE_ID_RE.search(cell_text(cell)) for row in table for cell in row):
                raise ValueError("Chybí hlavička tabulky usnesení")
            continue
        for row in table[1:]:
            if len(row) != len(table[0]):
                raise ValueError("Nesouhlasí počet sloupců tabulky usnesení")
            label = cell_text(row[columns["id"]])
            text = (row[columns["text"]] or "").strip()
            meeting_date = cell_text(row[columns["date"]])
            if not label:
                if not text:
                    continue
                if not rows:
                    raise ValueError("Pokračování textu bez čísla usnesení")
                previous = rows[-1]
                if meeting_date and previous[2] and parse_meeting_date(meeting_date) != parse_meeting_date(previous[2]):
                    raise ValueError("Pokračování usnesení obsahuje jiné datum jednání")
                previous[1] += "\n" + text
                previous[2] = previous[2] or meeting_date
                continue
            if not SOURCE_ID_RE.fullmatch(label):
                raise ValueError(f"Neplatné číslo usnesení: {label}")
            if label in seen:
                raise ValueError(f"Duplicitní usnesení: {label}")
            seen.add(label)
            rows.append([label, text, meeting_date])

    records = []
    for source_id, text, meeting_date in rows:
        parts = BODY_RE.split(text, maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError(f"Chybí text přijatého usnesení: {source_id}")
        title = re.sub(r"^\s*Bod\s+programu\s*:\s*", "", parts[0], flags=re.IGNORECASE)
        parts_id = require_resolution_id(source_id)
        datum = parse_meeting_date(meeting_date)
        if int(datum[:4]) != parts_id.year:
            raise ValueError(f"Rok čísla usnesení nesouhlasí s datem jednání: {source_id}")
        record = {
            "id": source_id,
            "datum": datum,
            "organ": ORGANS[SOURCE_ID_RE.fullmatch(source_id).group(1).upper()],
            "text_raw": parts[1].strip(),
            "source_format": "usneseni.cz",
            "agenda_title": cell_text(title),
        }
        if extra:
            record.update(extra)
        records.append(record)
    if not records:
        raise ValueError("Nenalezena tabulka přijatých usnesení")
    return records


def parse_pages(pages, extra: dict | None = None) -> list[dict]:
    clean_pages = [page.dedupe_chars() for page in pages]
    tables = (table for page in clean_pages for table in page.extract_tables())
    records = parse_tables(tables, extra)
    # Row headings in the text also catch tables or pages missed by table extraction.
    expected = set()
    for page in clean_pages:
        for line in (page.extract_text() or "").splitlines():
            match = SOURCE_ID_RE.match(line.strip())
            if match and re.match(r"\s+Bod\s+programu\s*:", line.strip()[match.end():], re.IGNORECASE):
                expected.add(match.group())
    if expected - {record["id"] for record in records}:
        raise ValueError("Čísla usnesení v textu a tabulkách PDF nesouhlasí")
    return records
