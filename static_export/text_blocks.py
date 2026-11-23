"""Separate explicit PDF list entries without changing their text or numbering."""

import re
from collections.abc import Callable


LIST_ITEM_RE = re.compile(r"^[ \t]*(?:(?P<number>[1-9]\d*)\.|(?P<bullet>[•●▪-]))[ \t]+(?=\S)", re.MULTILINE)


def render_text_blocks(text: str, render_inline: Callable[[str], str]) -> str:
    """Insert visual breaks only; every source character still reaches render_inline."""
    matches = list(LIST_ITEM_RE.finditer(text))
    if len(matches) < 2:
        return render_inline(text)
    numbered = matches[0].group("number") is not None
    if any((match.group("number") is not None) != numbered for match in matches):
        return render_inline(text)
    introduction = text[:matches[0].start()].strip()
    if numbered:
        numbers = [int(match.group("number")) for match in matches]
        if numbers != list(range(1, len(numbers) + 1)):
            return render_inline(text)
        # A pair of line-leading dates is not enough evidence of a numbered list.
        if introduction and not introduction.endswith(":"):
            return render_inline(text)
    parts = []
    cursor = 0
    for match in matches:
        if match.start() > cursor:
            parts.append(render_inline(text[cursor:match.start()]))
        if match.start():
            parts.append("<br><br>")
        cursor = match.start()
    parts.append(render_inline(text[cursor:]))
    return "".join(parts)
