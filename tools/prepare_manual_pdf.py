#!/usr/bin/env python3
"""Prepare one manually supplied Litovel PDF for CI processing."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

try:
    from sync_litovel_notices import DownloadedFile, slugify_pdf_name
except ImportError:
    from tools.sync_litovel_notices import DownloadedFile, slugify_pdf_name


USER_AGENT = "usneseni-mesta-litovel-manual-pdf/1.0 (+https://github.com/litovle/usneseni-mesta)"


@dataclass(frozen=True)
class ManualPdf:
    kind: str
    source: str
    path: str
    dry_run: bool


def github_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def safe_relative_path(path: Path) -> Path:
    if path.is_absolute():
        raise ValueError("pdf_path must be relative to the repository")
    normalized = Path(path)
    if ".." in normalized.parts:
        raise ValueError("pdf_path must not contain '..'")
    if normalized.parts[:1] != ("resources",):
        raise ValueError("pdf_path must be under resources/")
    if normalized.suffix.lower() != ".pdf":
        raise ValueError("pdf_path must point to a PDF")
    return normalized


def target_directory(document_type: str, resolution_target: str, resources_dir: Path, ro_dir: Path) -> Path:
    if document_type == "budget_change":
        return ro_dir
    if resolution_target == "zastupitelstvo":
        return resources_dir / "zastupitelstvo"
    return resources_dir / "rm"


def filename_from_headers(response: requests.Response) -> str | None:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition, re.IGNORECASE)
    if not match:
        return None
    return slugify_pdf_name(unquote(match.group(1)))


def filename_from_url(url: str) -> str | None:
    name = Path(unquote(urlparse(url).path)).name
    if not name or "." not in name:
        return None
    return slugify_pdf_name(name)


def download_pdf(url: str) -> tuple[bytes, requests.Response]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    response = session.get(url, timeout=60)
    response.raise_for_status()
    content = response.content
    if not content.lstrip().startswith(b"%PDF"):
        raise ValueError(f"Downloaded URL is not a PDF: {url}")
    return content, response


def destination_for_url(
    *,
    pdf_url: str,
    target_filename: str,
    document_type: str,
    resolution_target: str,
    resources_dir: Path,
    ro_dir: Path,
    response: requests.Response | None,
) -> Path:
    if target_filename:
        filename = slugify_pdf_name(target_filename)
    elif response:
        filename = filename_from_headers(response) or filename_from_url(pdf_url) or "manual_litovel_document.pdf"
    else:
        filename = filename_from_url(pdf_url) or "manual_litovel_document.pdf"
    return target_directory(document_type, resolution_target, resources_dir, ro_dir) / filename


def prepare_manual_pdf(
    *,
    document_type: str,
    pdf_path: str,
    pdf_url: str,
    target_filename: str,
    resolution_target: str,
    resources_dir: Path,
    ro_dir: Path,
    dry_run: bool,
) -> ManualPdf:
    if bool(pdf_path) == bool(pdf_url):
        raise ValueError("Provide exactly one of pdf_path or pdf_url")

    if pdf_path:
        path = safe_relative_path(Path(pdf_path))
        if not path.exists():
            raise FileNotFoundError(f"PDF path does not exist: {path}")
        return ManualPdf(kind=document_type, source=str(path), path=str(path), dry_run=dry_run)

    content = b""
    response = None
    if not dry_run:
        content, response = download_pdf(pdf_url)

    destination = destination_for_url(
        pdf_url=pdf_url,
        target_filename=target_filename,
        document_type=document_type,
        resolution_target=resolution_target,
        resources_dir=resources_dir,
        ro_dir=ro_dir,
        response=response,
    )

    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    return ManualPdf(kind=document_type, source=pdf_url, path=str(destination), dry_run=dry_run)


def write_manifest(path: Path, manual_pdf: ManualPdf) -> None:
    kind = "budget_change" if manual_pdf.kind == "budget_change" else "resolution"
    downloaded = DownloadedFile(
        kind=kind,
        key="manual",
        title="Ručně přidané PDF",
        detail_url=manual_pdf.source,
        pdf_url=manual_pdf.source,
        path=manual_pdf.path,
    )
    payload = {
        "dry_run": manual_pdf.dry_run,
        "found": True,
        "manual": asdict(manual_pdf),
        "downloaded": [asdict(downloaded)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_pr_body(path: Path, manual_pdf: ManualPdf) -> None:
    lines = [
        "Ručně spuštěné zpracování PDF z Litovle.",
        "",
        f"- typ: `{manual_pdf.kind}`",
        f"- PDF: `{manual_pdf.path}`",
        f"- zdroj: {manual_pdf.source}",
    ]
    if manual_pdf.dry_run:
        lines.append("")
        lines.append("Dry run only. No files were downloaded or parsed.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-type", choices=["resolution", "budget_change"], required=True)
    parser.add_argument("--pdf-path", default="")
    parser.add_argument("--pdf-url", default="")
    parser.add_argument("--target-filename", default="")
    parser.add_argument("--resolution-target", choices=["rm", "zastupitelstvo"], default="rm")
    parser.add_argument("--resources", type=Path, default=Path("resources"))
    parser.add_argument("--ro-pdf", type=Path, default=Path("resources/rozpoctova-opatreni"))
    parser.add_argument("--manifest", type=Path, default=Path(".litovel-manual-manifest.json"))
    parser.add_argument("--pr-body", type=Path, default=Path(".litovel-manual-pr-body.md"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manual_pdf = prepare_manual_pdf(
        document_type=args.document_type,
        pdf_path=args.pdf_path.strip(),
        pdf_url=args.pdf_url.strip(),
        target_filename=args.target_filename.strip(),
        resolution_target=args.resolution_target,
        resources_dir=args.resources,
        ro_dir=args.ro_pdf,
        dry_run=args.dry_run,
    )
    write_manifest(args.manifest, manual_pdf)
    write_pr_body(args.pr_body, manual_pdf)
    github_output("found", "true")
    github_output("dry_run", "true" if args.dry_run else "false")

    action = "Would process" if args.dry_run else "Prepared"
    print(f"{action}: {manual_pdf.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
