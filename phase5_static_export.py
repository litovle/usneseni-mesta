#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
phase5_static_export
====================

Export: jednou generuje stránky usnesení, RO a sitemap z finálních dat pro Jekyll.
--without-budget vypíná načítání i autodetekci RO; existující výstupy nemaže.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from static_export import (
    group_opatreni_by_content_year,
    load_opatreni_dir,
    meeting_from_id,
    render_budget_links_section,
    ro_slug_from_id,
    rz_anchor,
    write_meeting_index,
    write_resolution,
    write_ro_index,
    write_ro_page,
    write_year_index,
)


BASE_URL = "https://litovle.cz"


def write_sitemap(urls: List[str], output_root: Path, filename: str = "sitemap-usneseni.xml") -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for url in sorted(set(urls)):
        lines.append("  <url>")
        lines.append(f"    <loc>{BASE_URL}{url}</loc>")
        lines.append("  </url>")

    lines.append("</urlset>")
    (output_root / filename).write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 – static export of municipal resolutions")
    parser.add_argument("-i", "--input", type=Path, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--opatreni",
        type=Path,
        help="Adresář s propojenými JSON rozpočtových opatření; výchozí je sourozenec inputu rozpoctova-opatreni/",
    )
    parser.add_argument(
        "--sitemap-filename",
        default="sitemap-usneseni.xml",
        help="Název sitemap souboru pro generované stránky usnesení.",
    )
    parser.add_argument("--without-budget", action="store_true",
                        help="Exportovat pouze usnesení; vypnout načítání i autodetekci rozpočtových opatření.")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit("Input JSON does not exist.")

    args.output.mkdir(parents=True, exist_ok=True)

    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("Input JSON must be a list of resolutions.")

    opatreni_list = [] if args.without_budget else load_opatreni_dir(args.input, args.opatreni)

    refs_out_map: Dict[str, List[str]] = defaultdict(list)
    refs_in_map: Dict[str, List[str]] = defaultdict(list)
    for resolution in data:
        source = resolution.get("id")
        for ref in resolution.get("references_out", []):
            target = ref.get("resolved")
            if not target:
                continue
            refs_out_map[source].append(target)
            refs_in_map[target].append(source)

    by_year: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    by_meeting: Dict[str, List[Tuple[str, str, Optional[str], List[str]]]] = defaultdict(list)
    by_meeting_meta: Dict[str, Dict] = {}
    meetings_by_year: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    sitemap_urls: List[str] = []
    opatreni_by_content_year = group_opatreni_by_content_year(opatreni_list)

    for resolution in data:
        if not all(key in resolution for key in ("id", "datum", "organ")):
            continue

        year, rid, permalink, datum = write_resolution(resolution, args.output, refs_out_map, refs_in_map)
        by_year[year].append((rid, permalink, datum))
        sitemap_urls.append(permalink)

        org, meeting, year = meeting_from_id(rid)
        key = f"{year}/{org}-{meeting}"
        by_meeting[key].append((rid, permalink, resolution.get("subject"), resolution.get("actions", [])))

        if key not in by_meeting_meta:
            by_meeting_meta[key] = {
                "organ": resolution.get("organ"),
                "datum": resolution.get("datum"),
                "term_id": resolution.get("term_id"),
                "term_label": resolution.get("term_label"),
            }

        meeting_slug = f"{org}-{meeting}"
        meeting_url = f"/usneseni/{year}/{meeting_slug}/"
        meeting_date = resolution.get("datum")
        if not any(slug == meeting_slug for slug, _, _ in meetings_by_year[year]):
            meetings_by_year[year].append((meeting_slug, meeting_url, meeting_date))

    for year, entries in by_year.items():
        write_year_index(
            year,
            entries,
            meetings_by_year.get(year, []),
            args.output,
            opatreni_by_content_year.get(year, []),
        )
        sitemap_urls.append(f"/usneseni/{year}/")

    for key, entries in by_meeting.items():
        year, rest = key.split("/")
        org, meeting = rest.split("-")
        write_meeting_index(year, org, meeting, entries, by_meeting_meta[key], args.output)
        sitemap_urls.append(f"/usneseni/{year}/{org}-{meeting}/")

    if opatreni_list:
        sitemap_urls.append(write_ro_index(opatreni_list, args.output))
        for opatreni in opatreni_list:
            sitemap_urls.append(write_ro_page(opatreni, args.output))

    write_sitemap(sitemap_urls, args.output, args.sitemap_filename)

    print("PHASE 5 complete ✔")
    print(f"Resolutions: {len(data)}")
    print(f"Years: {len(by_year)}")
    print(f"Meetings: {len(by_meeting)}")
    if opatreni_list:
        print(f"Rozpočtová opatření: {len(opatreni_list)}")


__all__ = [
    "group_opatreni_by_content_year",
    "render_budget_links_section",
    "ro_slug_from_id",
    "rz_anchor",
    "write_year_index",
    "write_ro_page",
]


if __name__ == "__main__":
    main()
