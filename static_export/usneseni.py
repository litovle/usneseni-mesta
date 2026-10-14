from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .format import budget_change_count_label, format_date
from .paths import meeting_from_id, resolution_url, ro_url, rz_anchor, slug_from_id
from .ro_summary import summarize_opatreni_plain
from .topics import topic_category, topic_label


def organ_label(code: str) -> str:
    return {
        "RM": "Rada města",
        "ZM": "Zastupitelstvo",
    }.get(code, code)


def resolution_count_label(count: int) -> str:
    if count == 1:
        return "1 usnesení"
    if 2 <= count <= 4:
        return f"{count} usnesení"
    return f"{count} usnesení"


def render_back_link(
    default_href: str = "/usneseni/",
    default_label: str = "← Zpět na vyhledávání",
    allowed_prefixes: Optional[Tuple[str, ...]] = None,
    wrapper_class: Optional[str] = None,
) -> str:
    prefixes = allowed_prefixes or ("/usneseni",)
    checks = " || ".join(
        [f'url.pathname === "{prefix}" || url.pathname.startsWith("{prefix}/")' for prefix in prefixes]
    )
    wrapper_attr = f' class="{wrapper_class}"' if wrapper_class else ""
    return f"""
<p{wrapper_attr}>
  <a href="{default_href}" id="back-link">{default_label}</a>
</p>

<script>
(function() {{
  const a = document.getElementById("back-link");
  if (!a) return;

  const back = new URLSearchParams(location.search).get("back");
  try {{
    const url = new URL(back, location.origin);
    if (
      url.origin === location.origin &&
      ({checks})
    ) {{
      a.href = url.pathname + url.search;
      a.textContent = "← Zpět na vyhledávání";
    }}
  }} catch (e) {{
    // ignoruj rozbité hodnoty
  }}
}})();
</script>
"""


def render_meeting_link(resolution: Dict) -> str:
    rid = resolution["id"]
    org, meeting, year = meeting_from_id(rid)
    url = f"/usneseni/{year}/{org}-{meeting}/"
    return f"""
<p>
  <a href="{url}">
    → Všechna usnesení z této schůze
  </a>
</p>
"""


def render_resolution_content(resolution: Dict) -> str:
    parts: List[str] = [render_back_link(), render_meeting_link(resolution)]
    actions = resolution.get("actions", [])
    subject = resolution.get("subject")
    items = resolution.get("items", [])

    if subject and len(actions) == 1 and not items:
        parts.append(f"<p>{html.escape(actions[0])} {html.escape(subject)}</p>")
        return "\n".join(parts)

    if subject:
        parts.append(f"<p>{html.escape(subject)}</p>")

    for item in items:
        label = html.escape(item.get("label", ""))
        text = html.escape(item.get("text", ""))
        parts.append(f"<p><strong>{label})</strong> {text}</p>")

    if resolution.get("tail"):
        parts.append(f"<p>{html.escape(resolution['tail'])}</p>")

    return "\n".join(parts)


def render_references_section(title: str, ids: List[str]) -> str:
    if not ids:
        return ""

    lines = [f"<h2>{title}</h2>", "<ul>"]
    for rid in sorted(set(ids)):
        lines.append(f'<li><a href="{resolution_url(rid)}">{html.escape(rid)}</a></li>')
    lines.append("</ul>")
    return "\n".join(lines)


def budget_change_sort_key(value: str):
    match = re.match(r"^(\d+)/(\d{4})/(RM|ZM)$", value)
    if not match:
        return (9999, value)
    number, year, organ = match.groups()
    return (int(year), organ, int(number))


def render_budget_links_section(resolution: Dict) -> str:
    approved = resolution.get("budget_opatreni_approved") or []
    budget_links = resolution.get("budget_change_links") or []
    if not approved and not budget_links:
        return ""

    lines = ['<section class="usn-budget-links">', "<h2>Rozpočtová opatření</h2>"]

    seen_approved = set()
    approved_lines = []
    for link in approved:
        opatreni_id = link.get("opatreni_id")
        if not opatreni_id or opatreni_id in seen_approved:
            continue
        seen_approved.add(opatreni_id)
        approved_lines.append(f'<li><a href="{ro_url(opatreni_id)}">{html.escape(opatreni_id)}</a></li>')

    seen_budget_changes = set()
    budget_change_lines = []
    for link in sorted(budget_links, key=lambda item: budget_change_sort_key(item.get("budget_change_id", ""))):
        budget_change_id = link.get("budget_change_id")
        opatreni_id = link.get("opatreni_id")
        if not budget_change_id or not opatreni_id:
            continue

        key = (budget_change_id, opatreni_id)
        if key in seen_budget_changes:
            continue
        seen_budget_changes.add(key)

        url = ro_url(opatreni_id) + "#" + rz_anchor(budget_change_id)
        plain_title = (link.get("plain_title") or "").strip()
        affected_place = (link.get("affected_place") or "").strip()
        label = f"Rozpočtová změna {html.escape(budget_change_id)}"
        if plain_title:
            label += f": {html.escape(plain_title)}"
        if affected_place and affected_place.lower() not in plain_title.lower():
            label += f" ({html.escape(affected_place)})"
        budget_change_lines.append("<li>" f'<a href="{url}">{label}</a> ' f"v {html.escape(opatreni_id)}" "</li>")

    if approved_lines:
        lines.append("<h3>Odkazováno z rozpočtového opatření</h3>")
        lines.append("<ul>")
        lines.extend(approved_lines)
        lines.append("</ul>")

    if budget_change_lines:
        lines.append("<h3>Zmiňuje rozpočtové změny</h3>")
        lines.append(
            f'<details class="usn-budget-change-list" open>'
            f'<summary>{budget_change_count_label(len(budget_change_lines))}</summary>'
            "<ul>"
        )
        lines.extend(budget_change_lines)
        lines.append("</ul></details>")

    lines.append("</section>")
    return "\n".join(lines)


def write_resolution(
    resolution: Dict,
    output_root: Path,
    refs_out_map: Dict[str, List[str]],
    refs_in_map: Dict[str, List[str]],
) -> Tuple[str, str, str, str]:
    rid = resolution["id"]
    slug = slug_from_id(rid)
    year = resolution["datum"][:4]
    target_dir = output_root / "usneseni" / year / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    permalink = f"/usneseni/{year}/{slug}/"

    subject = resolution.get("subject")
    if subject:
        raw_desc = f"{resolution.get('organ', '')}, {resolution.get('datum', '')}: {subject}"
    else:
        raw_desc = f"{resolution.get('organ', '')}, {resolution.get('datum', '')}, usnesení {rid}"

    description = raw_desc[:157] + "…" if len(raw_desc) > 160 else raw_desc
    description = html.escape(description)

    frontmatter = (
        "---\n"
        "layout: usneseni\n"
        f'title: "Usnesení {rid}"\n'
        f'description: "{description}"\n'
        f'cislo: "{rid}"\n'
        f'organ: "{resolution.get("organ", "")}"\n'
        f'datum: "{resolution.get("datum", "")}"\n'
    )
    category = topic_category(resolution)
    if category:
        frontmatter += f"classification_category: {json.dumps(category, ensure_ascii=False)}\n"
        frontmatter += f"classification_label: {json.dumps(topic_label(category), ensure_ascii=False)}\n"
    if resolution.get("term_id"):
        frontmatter += f'term_id: "{resolution.get("term_id")}"\n'
    if resolution.get("term_label"):
        frontmatter += f'term_label: "{resolution.get("term_label")}"\n'
    frontmatter += (
        f"permalink: {permalink}\n"
        "---\n\n"
    )

    content = render_resolution_content(resolution)
    budget_links_section = render_budget_links_section(resolution)
    if budget_links_section:
        content += "\n" + budget_links_section
    content += render_references_section("Odkazuje na", refs_out_map.get(rid, []))
    content += render_references_section("Je odkazováno z", refs_in_map.get(rid, []))

    (target_dir / "index.html").write_text(frontmatter + content, encoding="utf-8")
    return year, rid, permalink, resolution.get("datum", "")


def write_year_index(
    year: str,
    entries: List[Tuple[str, str, str]],
    meetings: List[Tuple[str, str, str]],
    output_root: Path,
    opatreni_entries: Optional[List[Dict]] = None,
) -> None:
    target_dir = output_root / "usneseni" / year
    target_dir.mkdir(parents=True, exist_ok=True)

    rm = []
    zm = []
    for slug, url, date in meetings:
        if slug.startswith("RM-"):
            rm.append((slug, url, date))
        elif slug.startswith("ZM-"):
            zm.append((slug, url, date))

    def sort_meetings(items):
        return sorted(items, key=lambda item: int(item[0].split("-")[1]))

    def sort_resolutions(items):
        def key(item):
            rid, _, date = item
            org, number, meeting, rid_year = rid.split("/")
            return (
                date or "",
                rid_year,
                int(meeting),
                org,
                int(number),
            )

        return sorted(items, key=key, reverse=True)

    lines = [
        "---",
        "layout: usneseni_year",
        f"title: Usnesení {year}",
        f"permalink: /usneseni/{year}/",
        "---",
        "",
        f"<h1>Usnesení {year}</h1>",
    ]

    sorted_entries = sort_resolutions(entries)
    grouped_entries: Dict[Tuple[str, str], List[Tuple[str, str, str]]] = {}
    for entry in sorted_entries:
        rid, _, date = entry
        org, meeting, _ = meeting_from_id(rid)
        grouped_entries.setdefault((org, meeting), []).append(entry)

    lines += ["", "<h2>Schůze</h2>", '<div class="usn-year-groups">']
    for (org, meeting), meeting_entries in grouped_entries.items():
        meeting_date = meeting_entries[0][2]
        meeting_url = f"/usneseni/{year}/{org}-{meeting}/"
        lines += [
            '<details class="usn-year-group">',
            "<summary>",
            f'<span class="usn-year-group-title">{html.escape(organ_label(org))} · schůze {html.escape(meeting)}</span>',
            f'<span class="usn-date">{html.escape(format_date(meeting_date))}</span>',
            f'<span class="usn-year-group-count">{resolution_count_label(len(meeting_entries))}</span>',
            "</summary>",
            f'<p class="usn-more"><a href="{meeting_url}">Otevřít stránku schůze</a></p>',
            "<ul>",
        ]
        for rid, permalink, _ in meeting_entries:
            lines.append(f'<li><a href="{permalink}">{html.escape(rid)}</a></li>')
        lines += ["</ul>", "</details>"]
    lines.append("</div>")

    if opatreni_entries:
        lines += ["", "<h2>Rozpočtová opatření</h2>", '<div class="usn-year-ro-list">']
        for opatreni in sorted(
            opatreni_entries,
            key=lambda item: (item.get("approval_date") or "", item.get("year", 0), item.get("number", 0)),
            reverse=True,
        ):
            oid = opatreni["id"]
            approval_date = opatreni.get("approval_date") or ""
            plain_summary = summarize_opatreni_plain(opatreni)
            link = (
                f'<a href="{ro_url(oid)}">{html.escape(oid.replace("/", "-"))} '
                f'<span class="usn-date">{html.escape(format_date(approval_date))}</span></a>'
            )
            if plain_summary:
                lines.append(f'<div class="usn-year-ro-card">{link}<div class="usn-summary">{html.escape(plain_summary)}</div></div>')
            else:
                lines.append(f'<div class="usn-year-ro-card">{link}</div>')
        lines += [
            "</div>",
            '<p class="usn-more"><a href="/rozpoctova-opatreni/">Všechna rozpočtová opatření</a></p>',
        ]

    (target_dir / "index.html").write_text("\n".join(lines), encoding="utf-8")


def write_meeting_index(
    year: str,
    org: str,
    meeting: str,
    entries: List[Tuple[str, str, Optional[str], List[str]]],
    meta: Dict,
    output_root: Path,
) -> None:
    slug = f"{org}-{meeting}"
    target_dir = output_root / "usneseni" / year / slug
    target_dir.mkdir(parents=True, exist_ok=True)

    organ = meta.get("organ", "")
    datum = meta.get("datum") or ""
    term_label = meta.get("term_label") or ""
    meta_parts = [datum]
    if term_label:
        meta_parts.append(term_label)
    meta_parts.append(f"{len(entries)} usnesení")

    lines = [
        "---",
        "layout: usneseni_meeting",
        f"title: {organ} – schůze {meeting} ({year})",
        *([f'term_id: "{meta.get("term_id")}"'] if meta.get("term_id") else []),
        *([f'term_label: "{term_label}"'] if term_label else []),
        f"permalink: /usneseni/{year}/{slug}/",
        "---",
        "",
        f"<h1>{organ}: {meeting}. schůze</h1>",
        f'<p class="usn-meta">{html.escape(" • ".join(meta_parts))}</p>',
        "",
        '<ul class="usn-results">',
    ]

    for rid, permalink, subject, actions in sorted(entries):
        summary = ", ".join(actions) if actions else ""
        snippet = (subject or "").strip()
        if len(snippet) > 180:
            snippet = snippet[:177] + "…"

        lines.append(f"""
<li class="usn-result">
  <a href="{permalink}" class="usn-card">
    <div class="usn-head">
      <strong>{html.escape(rid)}</strong>
      <span class="usn-date">{html.escape(datum)}</span>
    </div>

    {f'<div class="usn-summary">{html.escape(summary)}</div>' if summary else ''}
    {f'<div class="usn-snippet">{html.escape(snippet)}</div>' if snippet else ''}
  </a>
</li>
""")

    lines.append("</ul>")
    (target_dir / "index.html").write_text("\n".join(lines), encoding="utf-8")
