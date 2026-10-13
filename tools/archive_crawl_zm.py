#!/usr/bin/env python3
"""Crawl Litovel historical ZM archive links into an inventory JSON."""

from __future__ import annotations

import argparse
import time
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag

try:
    from archive_zm_common import (
        ARCHIVE_URL,
        ORGAN,
        SOURCE,
        absolute_url,
        classify_url,
        normalize_ws,
        parse_title_metadata,
        stable_base_id,
        uniquify_id,
        write_json,
    )
except ImportError:
    from tools.archive_zm_common import (
        ARCHIVE_URL,
        ORGAN,
        SOURCE,
        absolute_url,
        classify_url,
        normalize_ws,
        parse_title_metadata,
        stable_base_id,
        uniquify_id,
        write_json,
    )


USER_AGENT = "usneseni-mesta-archive-zm-crawl/1.0 (+https://github.com/litovle/usneseni-mesta)"


def fetch_html(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(10, 90))
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise last_error or RuntimeError(f"Could not fetch {url}")


def main_content(soup: BeautifulSoup) -> Tag:
    article = soup.select_one("article.clanek_body")
    if article:
        return article
    fallback = soup.select_one(".clanek")
    if fallback:
        return fallback
    raise ValueError("Could not find archive article content.")


def heading_period(text: str) -> str | None:
    clean = normalize_ws(text)
    if "VOLEBNÍ OBDOBÍ" not in clean.upper():
        return None
    import re

    match = re.search(r"(\d{4})\s*[-–]\s*(\d{4})", clean)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return clean.replace("VOLEBNÍ OBDOBÍ", "").strip() or None


def heading_year(text: str) -> int | None:
    import re

    clean = normalize_ws(text)
    match = re.fullmatch(r"(19\d{2}|20\d{2})", clean)
    if match:
        return int(match.group(1))
    return None


def is_meaningful_archive_link(url_kind: str, title: str) -> bool:
    if url_kind == "direct_file":
        return bool(title)
    if url_kind == "flipbook":
        return bool(title)
    return False


def crawl_inventory(
    html: str,
    source_page_url: str = ARCHIVE_URL,
    *,
    source: str = SOURCE,
    organ: str = ORGAN,
    org_code: str = "ZM",
) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    content = main_content(soup)
    inventory: list[dict] = []
    used_ids: set[str] = set()
    direct_by_file_id: dict[str, str] = {}
    type_by_file_id: dict[str, str] = {}
    period: str | None = None
    year: int | None = None

    for element in content.descendants:
        if not isinstance(element, Tag):
            continue

        if element.name in {"h2", "h3", "h4", "h5"}:
            text = element.get_text(" ", strip=True)
            next_period = heading_period(text)
            if next_period:
                period = next_period
                continue
            next_year = heading_year(text)
            if next_year:
                year = next_year
                continue

        if element.name != "a" or not element.get("href"):
            continue

        href = element["href"]
        archive_url = absolute_url(href, source_page_url)
        title_attr = element.get("title", "")
        url_kind, filemanager_id, file_type, resolved_file_url = classify_url(archive_url, title_attr)
        title = normalize_ws(element.get_text(" ", strip=True)).strip(" ;")

        if url_kind == "direct_file" and filemanager_id:
            direct_by_file_id[filemanager_id] = archive_url
            type_by_file_id[filemanager_id] = file_type

        if url_kind == "flipbook" and filemanager_id and filemanager_id in direct_by_file_id:
            resolved_file_url = direct_by_file_id[filemanager_id]
            file_type = type_by_file_id.get(filemanager_id, file_type)

        if not is_meaningful_archive_link(url_kind, title):
            continue

        metadata = parse_title_metadata(title, year)
        base_id = stable_base_id(org_code, metadata["year"], metadata["meeting_no"], metadata["kind"])
        item_id = uniquify_id(base_id, archive_url, used_ids)
        status = "discovered"
        if url_kind == "flipbook" and not resolved_file_url:
            status = "needs_resolution"
        if url_kind == "unknown":
            status = "needs_resolution"

        inventory.append(
            {
                "id": item_id,
                "source": source,
                "source_page_url": source_page_url,
                "org": org_code,
                "organ": organ,
                "title": metadata["title"],
                "archive_href": href,
                "archive_url": archive_url,
                "period": period,
                "year": metadata["year"],
                "year_source": metadata["year_source"],
                "meeting_no": metadata["meeting_no"],
                "meeting_no_source": metadata["meeting_no_source"],
                "meeting_date": metadata["meeting_date"],
                "date_missing_reason": metadata["date_missing_reason"],
                "kind": metadata["kind"],
                "url_kind": url_kind,
                "filemanager_id": filemanager_id,
                "resolved_file_url": resolved_file_url,
                "file_type": file_type,
                "status": status,
            }
        )

    return sorted(
        inventory,
        key=lambda item: (
            item.get("period") or "",
            item.get("year") or 0,
            item.get("meeting_no") or 0,
            item.get("kind") or "",
            item.get("archive_url") or "",
            item.get("id") or "",
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=ARCHIVE_URL)
    parser.add_argument("--org-code", default="ZM")
    parser.add_argument("--organ", default=ORGAN)
    parser.add_argument("--source", default=SOURCE)
    parser.add_argument("--html", type=Path, help="Read archive HTML from a local fixture instead of HTTP.")
    parser.add_argument("--output", type=Path, default=Path("work/archive_zm/inventory.json"))
    args = parser.parse_args()

    html = args.html.read_text(encoding="utf-8") if args.html else fetch_html(args.url)
    inventory = crawl_inventory(html, args.url, source=args.source, organ=args.organ, org_code=args.org_code)
    write_json(args.output, inventory)

    print(f"Archive inventory written: {args.output}")
    print(f"Items: {len(inventory)}")
    needs_resolution = sum(1 for item in inventory if item.get("status") == "needs_resolution")
    if needs_resolution:
        print(f"Needs resolution: {needs_resolution}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
