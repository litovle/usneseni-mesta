"""Deterministic default icons from the existing resolution classification."""

import json
from pathlib import Path

from .models import InputError


DEFAULT_RESOLUTIONS_DIR = Path(__file__).resolve().parents[2] / "export" / "assets" / "usneseni" / "data"
# The classifier uses 0.70 in its review summary. Its scores are uncalibrated;
# this is only a publication review gate, never a probability claim.
REVIEW_SCORE = 0.70

# These are category defaults, not keyword guesses. The published topic can
# always use a more precise explicit `icon` in the input file.
CATEGORY_ICONS = {
    "administration": "committee",
    "culture": "culture",
    "education": "school",
    "environment": "environment",
    "finance": "coins",
    "infrastructure": "construction",
    "planning": "strategy",
    "property": "property",
    "security": "security",
    "social": "social",
    "sport": "sport",
    "strategy": "strategy",
    "transport": "road",
    "waste": "waste",
}


def _year_records(path: Path) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"Nelze načíst export usnesení {path}: {exc}") from exc
    if not isinstance(data, list):
        raise InputError(f"Export usnesení {path} musí obsahovat seznam záznamů.")
    return {record["id"]: record for record in data if isinstance(record, dict) and isinstance(record.get("id"), str)}


def icon_for_record(record: dict) -> str:
    """Choose the category default for an already loaded resolution record."""
    classification = record.get("classification") or {}
    if not isinstance(classification, dict):
        raise InputError(f"Usnesení {record.get('id', '?')} má neplatnou klasifikaci.")
    category = classification.get("category")
    icon = CATEGORY_ICONS.get(category)
    if icon is None:
        raise InputError(f"Usnesení {record.get('id', '?')} nemá podporovanou kategorii ({category!r}); zadejte icon ručně.")
    prediction = classification.get("prediction") or {}
    score = prediction.get("confidence") if isinstance(prediction, dict) else None
    if type(score) in (int, float) and score < REVIEW_SCORE:
        raise InputError(
            f"Usnesení {record.get('id', '?')} má nízké skóre klasifikace ({score:.2f}); "
            "zkontrolujte téma a zadejte icon ručně."
        )
    return icon


def get_resolution(resolution_id: str, data_dir: Path = DEFAULT_RESOLUTIONS_DIR) -> dict:
    parts = resolution_id.split("/")
    if len(parts) != 4 or parts[0] not in ("RM", "ZM") or not parts[3].isdigit():
        raise InputError(f"Neplatné resolution_id '{resolution_id}'. Očekávám např. RM/2568/81/2026.")
    path = data_dir / f"{parts[3]}.json"
    record = _year_records(path).get(resolution_id)
    if record is None:
        raise InputError(f"Usnesení {resolution_id} není v exportu {path}.")
    return record


def icon_for_resolution(resolution_id: str, data_dir: Path = DEFAULT_RESOLUTIONS_DIR) -> str:
    return icon_for_record(get_resolution(resolution_id, data_dir))
