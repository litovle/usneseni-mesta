"""Input parsing and validation. No layout decisions live here."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class InputError(ValueError):
    pass


def _mapping(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise InputError(f"{name} musí být objekt/mapa.")
    return value


def _text(value: Any, name: str, *, optional: bool = False, multiline: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{name} musí být neprázdný text.")
    result = value.strip()
    if not multiline and ("\n" in result or "\r" in result):
        raise InputError(f"{name} musí být na jednom řádku.")
    return result


@dataclass(frozen=True)
class WasteChange:
    place: str
    title_lines: tuple[str, ...]
    body: str
    accent_lines: tuple[int, ...]


@dataclass(frozen=True)
class Meeting:
    body: str
    session_label: str
    subtitle: str
    footer: str


@dataclass(frozen=True)
class Item:
    icon: str
    title: str
    text: str
    resolution_id: str | None = None


@dataclass(frozen=True)
class CouncilSummary:
    meeting: Meeting
    items: tuple[Item, ...]
    top_label: str | None


def parse_data(raw: Any, resolutions_dir: Path | None = None) -> WasteChange | CouncilSummary:
    data = _mapping(raw, "Kořen vstupu")
    kind = data.get("type")
    if kind == "waste_change":
        lines = data.get("title_lines")
        if not isinstance(lines, list) or not 2 <= len(lines) <= 5:
            raise InputError("title_lines musí obsahovat 2 až 5 řádků.")
        title_lines = tuple(_text(line, f"title_lines[{i}]") for i, line in enumerate(lines))
        accents = data.get("accent_lines", [len(lines)])
        if not isinstance(accents, list) or any(type(i) is not int or i < 1 or i > len(lines) for i in accents):
            raise InputError("accent_lines musí být seznam čísel řádků od 1 do počtu title_lines.")
        return WasteChange(
            place=_text(data.get("place"), "place"),
            title_lines=title_lines,
            body=_text(data.get("body"), "body", multiline=True),
            accent_lines=tuple(accents),
        )
    if kind == "council_summary":
        from .icon_selection import DEFAULT_RESOLUTIONS_DIR, get_resolution, icon_for_record

        source = _mapping(data.get("meeting"), "meeting")
        meeting = Meeting(
            body=_text(source.get("body"), "meeting.body"),
            session_label=_text(source.get("session_label"), "meeting.session_label"),
            subtitle=_text(source.get("subtitle"), "meeting.subtitle"),
            footer=_text(source.get("footer"), "meeting.footer", multiline=True),
        )
        source_items = data.get("items")
        if not isinstance(source_items, list) or len(source_items) not in (3, 4):
            raise InputError("items musí obsahovat právě 3 nebo 4 body.")
        items = []
        for index, source_item in enumerate(source_items):
            item = _mapping(source_item, f"items[{index}]")
            resolution_id = _text(item.get("resolution_id"), f"items[{index}].resolution_id", optional=True)
            record = get_resolution(resolution_id, resolutions_dir or DEFAULT_RESOLUTIONS_DIR) if resolution_id else None
            if item.get("icon") is None:
                if record is None:
                    raise InputError(f"items[{index}]: zadejte icon nebo resolution_id.")
                icon = icon_for_record(record)
            else:
                icon = _text(item.get("icon"), f"items[{index}].icon")
            items.append(Item(
                icon=icon,
                title=_text(item.get("title"), f"items[{index}].title", multiline=True),
                text=_text(item.get("text"), f"items[{index}].text", multiline=True),
                resolution_id=resolution_id,
            ))
        branding = _mapping(data.get("branding", {}), "branding")
        return CouncilSummary(meeting, tuple(items), _text(branding.get("top_label"), "branding.top_label", optional=True))
    raise InputError("type musí být 'waste_change' nebo 'council_summary'.")


def load_input(path: Path, resolutions_dir: Path | None = None) -> WasteChange | CouncilSummary:
    try:
        content = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            raw = json.loads(content)
        elif path.suffix.lower() in (".yaml", ".yml"):
            raw = yaml.safe_load(content)
        else:
            raise InputError("Vstup musí mít příponu .yaml, .yml nebo .json.")
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise InputError(f"Nelze načíst vstup {path}: {exc}") from exc
    return parse_data(raw, resolutions_dir)
