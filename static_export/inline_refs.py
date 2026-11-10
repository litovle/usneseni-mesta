"""Link documented resolution references while preserving their original wording."""
from __future__ import annotations

import html
import re
from typing import Dict, Optional

from .paths import resolution_url
from .relationships import RESOLUTION_ID
from tools.resolution_ids import parse_resolution_id, require_resolution_id


def render_inline_refs(text: str, resolution: Dict, records: Optional[Dict[str, Dict]]) -> str:
    text = text or ""
    if records is None:
        return html.escape(text)

    targets = {}
    for ref in resolution.get("references_out", []):
        raw, target = ref.get("raw"), ref.get("resolved")
        if not isinstance(raw, str) or not isinstance(target, str) or not RESOLUTION_ID.fullmatch(target):
            continue
        key = re.sub(r"\s+", "", raw).upper()
        if parse_resolution_id(key) is None and not re.fullmatch(r"\d+/\d+(?:/\d{4})?", key):
            continue
        targets.setdefault(key, set()).add(target)

    spans = []
    for raw, candidates in targets.items():
        # Ambiguous shorthand and unavailable documents remain plain text.
        if len(candidates) != 1:
            continue
        target = next(iter(candidates))
        if target not in records:
            continue
        pattern = r"\s*/\s*".join(re.escape(part) for part in raw.split("/"))
        shorthand = bool(re.fullmatch(r"\d+/\d+", raw))
        if shorthand:
            pattern += r"(?:\s*/\s*" + str(require_resolution_id(target).year) + r")?"
        ending = r"(?:(?![\w/])|(?=/[a-z](?:\W|$))"
        if shorthand:
            ending += r"|(?=[a-z]{1,2}(?:\W|$))"
        ending += ")"
        for match in re.finditer(r"(?<![\w/])" + pattern + ending, text, re.IGNORECASE):
            spans.append((match.start(), match.end(), target))

    spans.sort(key=lambda span: (span[0], -span[1]))
    result = []
    cursor = 0
    for start, end, target in spans:
        if start < cursor:
            continue
        result.append(html.escape(text[cursor:start]))
        result.append(f'<a class="usn-inline-ref usn-context-link" href="{resolution_url(target)}">'
                      f'{html.escape(text[start:end])}</a>')
        cursor = end
    result.append(html.escape(text[cursor:]))
    return "".join(result)
