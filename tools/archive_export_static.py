#!/usr/bin/env python3
"""Export archive search records as static detail pages."""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

try:
    from archive_build_search_index import archive_permalink, build_payload, read_promoted_document_ids
    from archive_zm_common import read_json
except ImportError:
    from tools.archive_build_search_index import archive_permalink, build_payload, read_promoted_document_ids
    from tools.archive_zm_common import read_json


ORG_LABELS = {
    "RM": "Rada města",
    "ZM": "Zastupitelstvo",
}


def archive_index_permalink() -> str:
    return "/usneseni/archiv/"


def archive_parent_permalink(parent_id: str) -> str:
    return f"/usneseni/archiv/{parent_id}/"


def front_matter(record: dict | None = None, *, title: str | None = None, description: str | None = None, permalink: str | None = None) -> str:
    record = record or {}
    page_title = title or record.get("title") or record.get("id") or "Archivní usnesení"
    if description is None:
        description_parts = [
            record.get("organ") or "Zastupitelstvo města Litovel",
            record.get("date") or "",
            "archivní usnesení" if record.get("type") == "archive_resolution" else "archivní dokument",
        ]
        description = ", ".join(part for part in description_parts if part)
    page_permalink = permalink or archive_permalink(record)
    return "\n".join(
        [
            "---",
            "layout: default",
            f'title: "{html.escape(page_title, quote=True)}"',
            f'description: "{html.escape(description, quote=True)}"',
            f"permalink: {page_permalink}",
            "---",
            "",
        ]
    )


def paragraphs(text: str) -> str:
    escaped = html.escape(text or "")
    return f'<pre class="usn-archive-text">{escaped}</pre>'


def source_link(record: dict) -> str:
    href = record.get("original_file_url") or record.get("source_url")
    if not href:
        return ""
    return (
        '<p class="usn-archive-source">'
        f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener">Původní dokument</a>'
        "</p>"
    )


def meeting_label(record: dict) -> str:
    return "schůze" if record.get("org") == "RM" else "zasedání"


def org_label(org: str | None) -> str:
    return ORG_LABELS.get(org or "", org or "Neznámý orgán")


def record_year(record: dict) -> str:
    year = record.get("year")
    if isinstance(year, int):
        return str(year)
    if isinstance(year, str) and year:
        return year
    date = record.get("date")
    if isinstance(date, str) and len(date) >= 4:
        return date[:4]
    return "unknown"


def year_sort_key(year: str) -> tuple[int, int | str]:
    if year.isdigit():
        return (0, -int(year))
    return (1, year)


def meeting_sort_value(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999999


def record_sort_key(record: dict) -> tuple:
    return (
        record.get("date") or "",
        meeting_sort_value(record.get("meeting_no")),
        record.get("resolution_no") or "",
        record.get("id") or "",
    )


def snippet(text: str, limit: int = 160) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def group_title(group: dict) -> str:
    parent = group["parent"]
    fallback = group["records"][0] if group["kind"] == "fallback" else {}
    return parent.get("title") or fallback.get("title") or group["id"]


def group_date(group: dict) -> str:
    return group["parent"].get("date") or group["records"][0].get("date") or ""


def group_period(group: dict) -> str:
    return group["parent"].get("period") or group["records"][0].get("period") or ""


def group_meeting_no(group: dict):
    return group["parent"].get("meeting_no") or group["records"][0].get("meeting_no")


def group_org(group: dict) -> str:
    return group["parent"].get("org") or group["records"][0].get("org") or ""


def group_year(group: dict) -> str:
    return record_year(group["parent"] or group["records"][0])


def build_archive_groups(records: list[dict], documents: list[dict]) -> list[dict]:
    documents_by_id = {record.get("id"): record for record in documents if record.get("id")}
    grouped: dict[str, dict] = {}

    for record in records:
        if record.get("type") == "archive_resolution" and record.get("parent_document_id"):
            group_id = record["parent_document_id"]
            group = grouped.setdefault(
                group_id,
                {
                    "id": group_id,
                    "kind": "split",
                    "parent": documents_by_id.get(group_id, {}),
                    "records": [],
                    "url": archive_parent_permalink(group_id),
                },
            )
            group["records"].append(record)
            continue

        group_id = record.get("id") or ""
        grouped[group_id] = {
            "id": group_id,
            "kind": "fallback",
            "parent": documents_by_id.get(group_id, record),
            "records": [record],
            "url": archive_permalink(record),
        }

    for group in grouped.values():
        if not group["parent"]:
            group["parent"] = group["records"][0]
        group["records"].sort(key=record_sort_key)

    return sorted(
        grouped.values(),
        key=lambda group: (
            year_sort_key(group_year(group)),
            group_org(group),
            group_date(group),
            meeting_sort_value(group_meeting_no(group)),
            group["id"],
        ),
    )


def render_page(record: dict) -> str:
    kind_label = "Archivní usnesení" if record.get("type") == "archive_resolution" else "Archivní dokument"
    metadata = [
        record.get("date") or "",
        record.get("period") and f"období {record.get('period')}",
        record.get("meeting_no") and f"{record.get('meeting_no')}. {meeting_label(record)}",
        record.get("resolution_no") and f"usnesení {record.get('resolution_no')}",
    ]
    lines = [
        front_matter(record),
        '<p><a href="/usneseni/" id="back-link">← Zpět na vyhledávání</a></p>',
        '<script src="/usneseni/back-link.js" defer></script>',
        f"<h1>{html.escape(record.get('title') or record.get('id') or kind_label)}</h1>",
        f'<p class="usn-info">{html.escape(kind_label)}</p>',
        f'<p class="usn-meta-detail">{html.escape(" · ".join(str(item) for item in metadata if item))}</p>',
        paragraphs(record.get("display_text") or record.get("search_text") or ""),
        source_link(record),
        "",
    ]
    return "\n".join(lines)


def render_parent_page(group: dict) -> str:
    parent = group["parent"]
    records = group["records"]
    title = group_title(group)
    metadata = [
        group_date(group),
        group_period(group) and f"období {group_period(group)}",
        group_meeting_no(group) and f"{group_meeting_no(group)}. {meeting_label(parent or records[0])}",
        f"{len(records)} usnesení",
    ]
    lines = [
        front_matter(
            parent,
            title=title,
            description=", ".join(str(item) for item in metadata if item),
            permalink=group["url"],
        ),
        '<p><a href="/usneseni/archiv/">← Zpět na archiv</a></p>',
        f"<h1>{html.escape(title)}</h1>",
        f'<p class="usn-info">Archivní dokument</p>',
        f'<p class="usn-meta-detail">{html.escape(" · ".join(str(item) for item in metadata if item))}</p>',
        source_link(parent),
        '<ol class="usn-archive-resolution-list">',
    ]
    for record in records:
        text = snippet(record.get("display_text") or record.get("search_text") or "")
        label = record.get("resolution_no") or record.get("id") or "Archivní usnesení"
        lines.append(
            "<li>"
            f'<a href="{html.escape(archive_permalink(record), quote=True)}">{html.escape(str(label))}</a>'
            f'<p>{html.escape(text)}</p>'
            "</li>"
        )
    lines.extend(["</ol>", ""])
    return "\n".join(lines)


def render_group_row(group: dict) -> str:
    title = group_title(group)
    metadata = [
        group_date(group),
        group_period(group) and f"období {group_period(group)}",
        group_meeting_no(group) and f"{group_meeting_no(group)}. {meeting_label(group['parent'] or group['records'][0])}",
    ]
    count_html = ""
    if group["kind"] == "split":
        count_label = f"{len(group['records'])} usnesení"
        count_html = f'<span class="usn-archive-meeting-count">{html.escape(count_label)}</span>'
    return (
        '<li class="usn-archive-meeting">'
        f'<a href="{html.escape(group["url"], quote=True)}">'
        f"<strong>{html.escape(title)}</strong>"
        f'<span class="usn-archive-meeting-meta">{html.escape(" · ".join(str(item) for item in metadata if item))}</span>'
        f"{count_html}"
        "</a>"
        "</li>"
    )


def render_archive_index(groups: list[dict], report: dict) -> str:
    years = sorted({group_year(group) for group in groups}, key=year_sort_key)
    year_range = ""
    numeric_years = sorted(int(year) for year in years if year.isdigit())
    if numeric_years:
        year_range = f"{numeric_years[0]}–{numeric_years[-1]}"

    lines = [
        front_matter(
            title="Archiv usnesení",
            description="Archivní usnesení Rady a Zastupitelstva města Litovel podle roků a schůzí.",
            permalink=archive_index_permalink(),
        ),
        '<p><a href="/usneseni/">← Zpět na vyhledávání</a></p>',
        "<h1>Archiv usnesení</h1>",
        '<p class="subtitle">Starší usnesení rady a zastupitelstva podle roků, orgánů a schůzí.</p>',
        '<div class="usn-archive-summary">',
        f"<span>{len(groups)} schůzí a dokumentů</span>",
        f"<span>{report.get('indexed_archive_resolutions', 0)} archivních usnesení</span>",
        f"<span>{report.get('fallback_archive_documents', 0)} nerozdělených dokumentů</span>",
        f"<span>{html.escape(year_range)}</span>" if year_range else "",
        "</div>",
        '<div class="usn-archive-years">',
    ]

    groups_by_year = {year: [group for group in groups if group_year(group) == year] for year in years}
    for index, year in enumerate(years):
        year_groups = groups_by_year[year]
        lines.extend(
            [
                '<details class="usn-year-group" open>' if index == 0 else '<details class="usn-year-group">',
                "<summary>",
                f'<span class="usn-year-group-title">{html.escape(year)}</span>',
                f'<span class="usn-year-group-count">{len(year_groups)} schůzí/dokumentů</span>',
                "</summary>",
            ]
        )
        for org in ("RM", "ZM", ""):
            org_groups = [group for group in year_groups if group_org(group) == org]
            if not org_groups:
                continue
            lines.append(f"<h2>{html.escape(org_label(org))}</h2>")
            lines.append('<ul class="usn-archive-meetings">')
            for group in org_groups:
                lines.append(render_group_row(group))
            lines.append("</ul>")
        lines.append("</details>")

    lines.extend(["</div>", ""])
    return "\n".join(line for line in lines if line != "")


def export_records(records: list[dict], output: Path) -> int:
    count = 0
    for record in records:
        permalink = archive_permalink(record).strip("/")
        page_dir = output / permalink
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(render_page(record), encoding="utf-8")
        count += 1
    return count


def export_archive_indexes(groups: list[dict], report: dict, output: Path) -> int:
    archive_root = output / "usneseni" / "archiv"
    archive_root.mkdir(parents=True, exist_ok=True)
    (archive_root / "index.html").write_text(render_archive_index(groups, report), encoding="utf-8")

    count = 1
    for group in groups:
        if group["kind"] != "split":
            continue
        page_dir = archive_root / group["id"]
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "index.html").write_text(render_parent_page(group), encoding="utf-8")
        count += 1
    return count


def read_json_lists(paths: list[Path]) -> list[dict]:
    combined: list[dict] = []
    for path in paths:
        records = read_json(path, [])
        if not isinstance(records, list):
            raise SystemExit(f"Archive export input must be a JSON list: {path}")
        combined.extend(records)
    return combined


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=[Path("work/archive_zm/archive_documents.json")],
        help="One or more archive_documents.json inputs.",
    )
    parser.add_argument(
        "--resolutions",
        type=Path,
        nargs="*",
        default=[Path("work/archive_zm/archive_resolutions.json")],
        help="Optional archive_resolutions.json child-record inputs.",
    )
    parser.add_argument(
        "--promoted-report",
        type=Path,
        nargs="*",
        default=[],
        help="Optional archive_current_promoted.json reports. Promoted documents are excluded from archive output.",
    )
    parser.add_argument("--output", type=Path, default=Path("export"))
    args = parser.parse_args()

    documents = read_json_lists(args.input)
    resolutions = read_json_lists(args.resolutions)
    promoted_document_ids = read_promoted_document_ids(args.promoted_report)

    by_year, report = build_payload(documents, resolutions, promoted_document_ids)
    records = [record for items in by_year.values() for record in items]
    groups = build_archive_groups(records, documents)
    count = export_records(records, args.output)
    index_count = export_archive_indexes(groups, report, args.output)
    print(f"Archive detail pages written: {count}")
    print(f"Archive index pages written: {index_count}")
    print(f"Archive resolutions: {report['indexed_archive_resolutions']}")
    print(f"Fallback archive documents: {report['fallback_archive_documents']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
