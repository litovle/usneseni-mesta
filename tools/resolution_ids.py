"""Read resolution-number metadata without changing the official identifier."""

import re
from dataclasses import dataclass


SLASH_ID_RE = re.compile(r"(RM|ZM)/(\d+)/(\d+)/(\d{4})", re.IGNORECASE)
USNESENI_CZ_ID_RE = re.compile(r"\bU([RZ])-(\d+)-(\d+)/(\d{4}|\d{2})\b", re.IGNORECASE)
RESOLUTION_ID_RE = re.compile(r"(?:(?:RM|ZM)/\d+/\d+/\d{4}|U[RZ]-\d+-\d+/(?:\d{4}|\d{2}))", re.IGNORECASE)


@dataclass(frozen=True)
class ResolutionParts:
    organ: str
    number: int
    meeting: int
    year: int
    scheme: str


def parse_resolution_id(value: str) -> ResolutionParts | None:
    if not isinstance(value, str):
        return None
    match = SLASH_ID_RE.fullmatch(value)
    if match:
        organ, number, meeting, year = match.groups()
        return ResolutionParts(organ.upper(), int(number), int(meeting), int(year), "slash")
    match = USNESENI_CZ_ID_RE.fullmatch(value)
    if match:
        organ, number, meeting, year = match.groups()
        full_year = int(year) + (2000 if len(year) == 2 else 0)
        return ResolutionParts("RM" if organ.upper() == "R" else "ZM", int(number), int(meeting), full_year, "usneseni.cz")
    return None


def require_resolution_id(value: str) -> ResolutionParts:
    parts = parse_resolution_id(value)
    if parts is None:
        raise ValueError(f"Unsupported resolution ID: {value!r}")
    return parts
