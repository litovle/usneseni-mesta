#!/usr/bin/env python3
"""Crawl Litovel RM archive links into an inventory JSON."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

try:
    from archive_crawl_zm import crawl_inventory
    from archive_zm_common import SOURCE, write_json
except ImportError:
    from tools.archive_crawl_zm import crawl_inventory
    from tools.archive_zm_common import SOURCE, write_json


ARCHIVE_URL = "https://www.litovel.eu/cs/mesto/rada-mesta/usneseni-rady-archiv.html"
ORGAN = "Rada města Litovel"
ORG_CODE = "RM"
USER_AGENT = "usneseni-mesta-archive-rm-crawl/1.0 (+https://github.com/litovle/usneseni-mesta)"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=ARCHIVE_URL)
    parser.add_argument("--html", type=Path, help="Read archive HTML from a local fixture instead of HTTP.")
    parser.add_argument("--output", type=Path, default=Path("work/archive_rm/inventory.json"))
    args = parser.parse_args()

    html = args.html.read_text(encoding="utf-8") if args.html else fetch_html(args.url)
    inventory = crawl_inventory(
        html,
        args.url,
        source=SOURCE,
        organ=ORGAN,
        org_code=ORG_CODE,
    )
    write_json(args.output, inventory)

    print(f"Archive inventory written: {args.output}")
    print(f"Items: {len(inventory)}")
    needs_resolution = sum(1 for item in inventory if item.get("status") == "needs_resolution")
    if needs_resolution:
        print(f"Needs resolution: {needs_resolution}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
