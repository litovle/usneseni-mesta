"""Render documented links between decisions without inferring their legal status."""
from __future__ import annotations

import html
import re
from typing import Callable, Dict, List

from .format import format_full_date
from .paths import resolution_url
from tools.resolution_ids import RESOLUTION_ID_RE


RESOLUTION_ID = RESOLUTION_ID_RE


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def reference_parts(source: Dict, target_id: str, revocations_only: bool = False) -> List[Dict]:
    """Associate a resolved reference with its actual paragraph, preserving item indices."""
    refs = [ref for ref in source.get("references_out", [])
            if ref.get("resolved") == target_id and ref.get("raw")]
    if not refs:
        return []
    paragraphs = [{"anchor": f"bod-{index}", "label": str(item.get("label") or ""),
                   "text": item.get("text") or ""}
                  for index, item in enumerate(source.get("items") or [], start=1)]
    subject = source.get("subject") or ""
    actions = source.get("actions") or []
    root_revocation = not paragraphs and any(normalized(action) == "revokuje" for action in actions)
    if subject:
        text = f"{actions[0]} {subject}" if not paragraphs and len(actions) == 1 else subject
        paragraphs.insert(0, {"anchor": "predmet", "label": "", "text": text})
    if source.get("tail"):
        paragraphs.append({"anchor": "dovetek", "label": "", "text": source["tail"]})

    matches = []
    for paragraph in paragraphs:
        text = normalized(paragraph["text"])
        action_text = re.sub(r"^(?:rada|zastupitelstvo) města litovel[ ,]+", "", text)
        if revocations_only and not (root_revocation or re.match(r"^revokuje(?:\s|[.:]|$)", action_text)):
            continue
        for ref in refs:
            raw = normalized(ref["raw"])
            raw_pattern = re.escape(raw) + (r"(?:/\d{4})?" if re.fullmatch(r"\d+/\d+", raw) else "")
            occurrence = re.search(r"(?<![\w/])" + raw_pattern + r"(?![\w/])", text)
            # A final /b is an explicit point suffix, not another resolution identifier.
            if not occurrence:
                occurrence = re.search(r"(?<![\w/])" + raw_pattern + r"(?=/[a-z](?:\W|$))", text)
            if not occurrence:
                continue
            suffix = text[occurrence.end():]
            suffix = re.split(r"\b(?:(?:rm|zm)/\d+|u[rz]-\d+-\d+/\d+)", suffix, maxsplit=1)[0][:160]
            point = re.match(r"/([a-z])(?:\W|$)", suffix) or re.search(
                r"\b(?:bod|bodu|bodem|odstavec|odstavce)\s+(?:ad\s+)?([a-z])(?:\)|(?=\s|[.,]|$))", suffix)
            matches.append({**paragraph, "target_label": point.group(1) if point else ""})
            break
    return matches


def point_anchor(record: Dict, label: str) -> str:
    matching = [index for index, item in enumerate(record.get("items") or [], start=1)
                if label and normalized(str(item.get("label") or "")) == normalized(label)]
    return f"bod-{matching[0]}" if len(matching) == 1 else ""


def dated(record: Dict) -> str:
    date = record.get("datum") or ""
    return f'<time datetime="{html.escape(date, quote=True)}">{html.escape(format_full_date(date))}</time>' if date else ""


def render_later_revocations(record: Dict, incoming: List[str], records: Dict[str, Dict], truncate: Callable) -> str:
    entries = []
    for source_id in sorted(set(incoming), key=lambda rid: (records.get(rid, {}).get("datum", ""), rid)):
        source = records.get(source_id)
        if not source or not source.get("datum") or source["datum"] < record.get("datum", ""):
            continue
        for part in reference_parts(source, record["id"], revocations_only=True):
            url = resolution_url(source_id) + "#" + part["anchor"]
            label = f' · bod {part["label"]})' if part["label"] else ""
            target_anchor = point_anchor(record, part["target_label"])
            target_link = (f'<a class="usn-context-link" href="#{target_anchor}">'
                           f'Odkazovaný bod {html.escape(part["target_label"])}) tohoto usnesení</a>') if target_anchor else ""
            entries.append('<li><div class="usn-context-meta">'
                           f'<a class="usn-context-link" href="{html.escape(url, quote=True)}">{html.escape(source_id + label)}</a> '
                           f'{dated(source)}</div><p class="usn-revision-quote">{html.escape(truncate(part["text"], 240))}</p>'
                           f'{target_link}</li>')
    if not entries:
        return ""
    return ('<aside class="usn-revision-notice" aria-labelledby="usn-revision-title">'
            '<h2 id="usn-revision-title">Pozdější revokace</h2>'
            '<p class="usn-context-note">V pozdějších usneseních je uvedeno:</p>'
            '<ul>' + "".join(entries) + '</ul></aside>')


def render_decision_history(record: Dict, outgoing: List[str], incoming: List[str], records: Dict[str, Dict], preview: Callable) -> str:
    outgoing = {rid for rid in outgoing if RESOLUTION_ID.fullmatch(rid) and rid != record["id"]}
    incoming = {rid for rid in incoming if RESOLUTION_ID.fullmatch(rid) and rid != record["id"]}
    related = outgoing | incoming
    if not related:
        return ""
    available = related & records.keys()
    rows = []
    for rid in sorted(available | {record["id"]}, key=lambda rid: (records[rid].get("datum", ""), rid)):
        entry = records[rid]
        if rid == record["id"]:
            rows.append('<li class="usn-result usn-history-current" aria-current="true">'
                        f'<div class="usn-head"><strong>{html.escape(rid)}</strong> {dated(entry)}</div>'
                        '<p class="usn-history-relation">Právě čtete</p></li>')
            continue
        if rid in incoming:
            revocations = reference_parts(entry, record["id"], revocations_only=True)
            parts = revocations or reference_parts(entry, record["id"])
            anchor = parts[0]["anchor"] if parts else ""
            relation = "Obsahuje revokaci" if revocations else "Odkazuje na toto usnesení"
        else:
            revocations = reference_parts(record, rid, revocations_only=True)
            anchor = point_anchor(entry, revocations[0]["target_label"]) if revocations else ""
            relation = "Revokace v tomto usnesení" if revocations else "Odkaz v tomto usnesení"
        if rid in incoming and rid in outgoing:
            relation += " · vzájemné odkazy"
        url = resolution_url(rid) + ("#" + anchor if anchor else "")
        rows.append('<li class="usn-result"><a class="usn-card usn-context-link" '
                    f'href="{html.escape(url, quote=True)}"><div class="usn-head">'
                    f'<strong>{html.escape(rid)}</strong> {dated(entry)}</div>'
                    f'<p class="usn-history-relation">{relation}</p>{preview(entry)}</a></li>')
    missing = sorted(related - available)
    unavailable = ('<ul class="usn-history-unavailable">' + "".join(
        f'<li><strong>{html.escape(rid)}</strong> — text zatím není dostupný.</li>' for rid in missing) + '</ul>') if missing else ""
    return ('<section class="usn-section usn-decision-history" aria-labelledby="usn-history-title">'
            '<h2 id="usn-history-title">Vývoj rozhodnutí</h2>'
            '<p class="usn-context-note">Seřazeno podle data. Přehled vychází z přímých odkazů v dostupných textech.</p>'
            '<ol class="usn-results">' + "".join(rows) + '</ol>' + unavailable + '</section>')
