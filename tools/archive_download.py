#!/usr/bin/env python3
"""Download direct filemanager files from a Litovel ZM archive inventory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

try:
    from archive_zm_common import read_json, resolved_file_url_from_id, write_json
except ImportError:
    from tools.archive_zm_common import read_json, resolved_file_url_from_id, write_json


USER_AGENT = "usneseni-mesta-archive-zm-download/1.0 (+https://github.com/litovle/usneseni-mesta)"


def resolve_flipbook_url(item: dict, session: requests.Session) -> str | None:
    if item.get("resolved_file_url"):
        return item["resolved_file_url"]

    filemanager_id = item.get("filemanager_id")
    file_type = item.get("file_type")
    if not filemanager_id:
        return None

    candidates = []
    if file_type in {"pdf", "doc", "docx"}:
        candidates.append(resolved_file_url_from_id(filemanager_id, file_type))
    candidates.extend(
        resolved_file_url_from_id(filemanager_id, ext)
        for ext in ("pdf", "doc", "docx")
        if ext != file_type
    )

    for candidate in [url for url in candidates if url]:
        try:
            response = session.get(candidate, stream=True, timeout=20)
            response.close()
        except requests.RequestException:
            continue
        content_type = response.headers.get("content-type", "").lower()
        if response.status_code == 200 and (
            "pdf" in content_type
            or "msword" in content_type
            or "officedocument" in content_type
            or Path(candidate).suffix.lower() in {".pdf", ".doc", ".docx"}
        ):
            item["file_type"] = Path(candidate).suffix.lower().lstrip(".")
            return candidate

    return None


def local_file_path(item: dict, files_dir: Path) -> Path:
    file_type = item.get("file_type") or "unknown"
    suffix = file_type if file_type in {"pdf", "doc", "docx"} else "bin"
    return files_dir / f"{item['id']}.{suffix}"


def download_inventory(inventory: list[dict], files_dir: Path) -> list[dict]:
    files_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for item in inventory:
        item.pop("download_error", None)

        url = item.get("resolved_file_url")
        if item.get("url_kind") == "flipbook" and not url:
            url = resolve_flipbook_url(item, session)
            if url:
                item["resolved_file_url"] = url

        if not url:
            item["status"] = "needs_resolution"
            continue

        destination = local_file_path(item, files_dir)
        try:
            response = session.get(url, timeout=60)
            response.raise_for_status()
            destination.write_bytes(response.content)
        except Exception as exc:
            item["status"] = "failed"
            item["download_error"] = str(exc)
            continue

        item["status"] = "downloaded"
        item["local_path"] = str(destination)
        item["downloaded_bytes"] = destination.stat().st_size

    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=Path("work/archive_zm/inventory.json"))
    parser.add_argument("--files-dir", type=Path, default=Path("work/archive_zm/files"))
    parser.add_argument("--output", type=Path, default=Path("work/archive_zm/inventory.json"))
    args = parser.parse_args()

    inventory = read_json(args.inventory, [])
    if not isinstance(inventory, list):
        raise SystemExit("Inventory must be a JSON list.")

    updated = download_inventory(inventory, args.files_dir)
    write_json(args.output, updated)
    print(f"Inventory updated: {args.output}")
    print(f"Downloaded: {sum(1 for item in updated if item.get('status') == 'downloaded')}")
    print(f"Needs resolution: {sum(1 for item in updated if item.get('status') == 'needs_resolution')}")
    print(f"Failed: {sum(1 for item in updated if item.get('status') == 'failed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
