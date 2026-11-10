from __future__ import annotations

from typing import Tuple

from tools.resolution_ids import require_resolution_id


def slug_from_id(resolution_id: str) -> str:
    return resolution_id.replace("/", "-")


def ro_slug_from_id(opatreni_id: str) -> str:
    return opatreni_id.replace("/", "-")


def ro_url(opatreni_id: str) -> str:
    return f"/rozpoctova-opatreni/{ro_slug_from_id(opatreni_id)}/"


def rz_anchor(budget_change_id: str) -> str:
    return "rz-" + budget_change_id.replace("/", "-").lower()


def resolution_url(resolution_id: str) -> str:
    slug = slug_from_id(resolution_id)
    year = require_resolution_id(resolution_id).year
    return f"/usneseni/{year}/{slug}/"


def meeting_from_id(rid: str) -> Tuple[str, str, str]:
    parts = require_resolution_id(rid)
    return parts.organ, str(parts.meeting), str(parts.year)
