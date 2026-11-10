"""Read adopted resolutions from a tabular PDF export."""

import re
import unicodedata
from datetime import date

try:
    from resolution_ids import PREFIXED_ID_RE, require_resolution_id
except ImportError:
    from tools.resolution_ids import PREFIXED_ID_RE, require_resolution_id

ORGANS = {"R": "Rada města Litovel", "Z": "Zastupitelstvo města Litovel"}
HEADERS = {"číslo usnesení": "id", "text usnesení": "text", "datum jednání": "date",
           "hlasování": "voting"}
BODY_RE = re.compile(r"Text\s+přijatého\s+usnesení\s*:\s*", re.IGNORECASE)
VOTE_GROUP_RE = re.compile(r"\b(proti|pro|zdr[žz]el\s+se)\s*:", re.IGNORECASE)
VOTE_COUNT_RE = re.compile(r"(?:\((\d+)\)|(\d+))(?=\s|$|[,;])")
VOTE_KEYS = {"pro": "for", "proti": "against", "zdržel se": "abstained", "zdrzel se": "abstained"}
NAME_SUFFIX_RE = re.compile(r"(?:[a-z]+\.)+|MBA|MPA|BBA|LLM|MSc", re.IGNORECASE)


def is_tabular_resolution_pdf(text: str) -> bool:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    folded = " ".join(folded.split())
    # Wrapped column headings can interleave in extracted text; voting is optional.
    return bool(PREFIXED_ID_RE.search(text)) and all(
        label in folded for label in ("cislo", "text usneseni", "datum", "jednani")
    )


def cell_text(value: str | None) -> str:
    return " ".join((value or "").split())


def parse_meeting_date(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", cell_text(value))
    if not match:
        raise ValueError(f"Neplatné datum jednání: {value!r}")
    day, month, year = map(int, match.groups())
    return date(year, month, day).isoformat()


def parse_voters(text: str) -> list[str]:
    """Keep comma-separated qualifications attached to the preceding person's name."""
    voters = []
    for part in re.split(r"[,;]", text):
        name = cell_text(part)
        if not name:
            continue
        if NAME_SUFFIX_RE.fullmatch(name):
            if not voters:
                raise ValueError("Titul bez jména v hlasování")
            voters[-1] += ", " + name
        else:
            if not any(character.isalpha() for character in name):
                raise ValueError("Neplatné jméno v hlasování")
            voters.append(name)
    return voters


def parse_voting(text: str | None) -> dict | None:
    """Read only reported counts and names; retain the original cell for verification."""
    raw = (text or "").strip()
    if not raw:
        return None
    groups = list(VOTE_GROUP_RE.finditer(raw))
    if not groups or raw[:groups[0].start()].strip():
        raise ValueError("Neplatný začátek hlasování")
    result = {}
    for index, match in enumerate(groups):
        key = VOTE_KEYS[cell_text(match.group(1)).lower()]
        if key in result:
            raise ValueError(f"Opakovaná skupina hlasování: {key}")
        end = groups[index + 1].start() if index + 1 < len(groups) else len(raw)
        content = raw[match.end():end].strip()
        count_match = VOTE_COUNT_RE.match(content)
        if not count_match:
            raise ValueError(f"Chybí platný počet hlasů: {key}")
        count = int(count_match.group(1) or count_match.group(2))
        names_text = content[count_match.end():].strip(" \n\r\t,;")
        voters = parse_voters(names_text) if names_text else ([] if count == 0 else None)
        if voters is not None and len(voters) != count:
            raise ValueError(f"Počet jmen neodpovídá počtu hlasů: {key}")
        result[key] = {"count": count, "voters": voters}
    if result.keys() != {"for", "against", "abstained"}:
        raise ValueError("Hlasování neobsahuje všechny skupiny pro, proti a zdržel se")
    return {key: result[key] for key in ("for", "against", "abstained")} | {"raw": raw}


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
        if not {"id", "text", "date"}.issubset(columns):
            if any(PREFIXED_ID_RE.search(cell_text(cell)) for row in table for cell in row):
                raise ValueError("Chybí hlavička tabulky usnesení")
            continue
        for row in table[1:]:
            if len(row) != len(table[0]):
                raise ValueError("Nesouhlasí počet sloupců tabulky usnesení")
            label = cell_text(row[columns["id"]])
            text = (row[columns["text"]] or "").strip()
            meeting_date = cell_text(row[columns["date"]])
            voting = (row[columns["voting"]] or "").strip() if "voting" in columns else ""
            if not label:
                if not text and not voting:
                    continue
                if not rows:
                    raise ValueError("Pokračování textu bez čísla usnesení")
                previous = rows[-1]
                if meeting_date and previous["date"] and parse_meeting_date(meeting_date) != parse_meeting_date(previous["date"]):
                    raise ValueError("Pokračování usnesení obsahuje jiné datum jednání")
                for key, value in (("text", text), ("voting", voting)):
                    if value:
                        previous[key] = (previous[key] + "\n" + value).strip()
                previous["date"] = previous["date"] or meeting_date
                continue
            if not PREFIXED_ID_RE.fullmatch(label):
                raise ValueError(f"Neplatné číslo usnesení: {label}")
            if label in seen:
                raise ValueError(f"Duplicitní usnesení: {label}")
            seen.add(label)
            rows.append({"id": label, "text": text, "date": meeting_date, "voting": voting})

    records = []
    for row in rows:
        source_id = row["id"]
        parts = BODY_RE.split(row["text"], maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            raise ValueError(f"Chybí text přijatého usnesení: {source_id}")
        title = re.sub(r"^\s*Bod\s+programu\s*:\s*", "", parts[0], flags=re.IGNORECASE)
        parts_id = require_resolution_id(source_id)
        datum = parse_meeting_date(row["date"])
        if int(datum[:4]) != parts_id.year:
            raise ValueError(f"Rok čísla usnesení nesouhlasí s datem jednání: {source_id}")
        record = {
            "id": source_id,
            "datum": datum,
            "organ": ORGANS[PREFIXED_ID_RE.fullmatch(source_id).group(1).upper()],
            "text_raw": parts[1].strip(),
            "source_format": "tabular",
            "agenda_title": cell_text(title),
        }
        try:
            voting = parse_voting(row["voting"])
        except ValueError as error:
            raise ValueError(f"{source_id}: {error}") from error
        if voting is not None:
            record["voting"] = voting
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
            match = PREFIXED_ID_RE.match(line.strip())
            if match and re.match(r"\s+Bod\s+programu\s*:", line.strip()[match.end():], re.IGNORECASE):
                expected.add(match.group())
    if expected - {record["id"] for record in records}:
        raise ValueError("Čísla usnesení v textu a tabulkách PDF nesouhlasí")
    return records
