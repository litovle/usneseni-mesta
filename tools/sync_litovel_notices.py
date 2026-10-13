#!/usr/bin/env python3
"""Download newly published Litovel resolution and budget-change PDFs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.litovel.eu"
NOTICE_BOARD_URL = f"{BASE_URL}/cs/urad/uredni-deska/aktualni-oznameni.html"
USER_AGENT = "usneseni-mesta-litovel-sync/1.0 (+https://github.com/litovle/usneseni-mesta)"


@dataclass(frozen=True)
class Notice:
    kind: str
    key: str
    title: str
    detail_url: str
    posted: str
    source: str
    notice_type: str


@dataclass(frozen=True)
class Attachment:
    url: str
    label: str


@dataclass(frozen=True)
class DownloadedFile:
    kind: str
    key: str
    title: str
    detail_url: str
    pdf_url: str
    path: str


def normalize_ws(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def fold_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def slugify_pdf_name(value: str) -> str:
    value = fold_ascii(normalize_ws(value)).lower()
    value = value.replace("/", "_")
    value = re.sub(r"[^a-z0-9.]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_.")
    if not value:
        value = "litovel_dokument"
    if not value.endswith(".pdf"):
        value += ".pdf"
    return value


def parse_budget_key(value: str) -> str | None:
    folded = fold_ascii(value).lower()
    if "rozpoct" not in folded:
        return None
    match = re.search(r"(?:c\.?|c_|c\._)?\s*(\d{1,4})\s*[/_. ]+\s*(20\d{2}|19\d{2})", folded)
    if not match:
        return None
    return f"RO/{int(match.group(1))}/{match.group(2)}"


def parse_resolution_key(value: str) -> str | None:
    folded = fold_ascii(value).lower()

    id_match = re.search(r"\b(rm|zm)\s*/\s*\d+\s*/\s*(\d+)\s*/\s*(20\d{2}|19\d{2})\b", folded)
    if id_match:
        return f"{id_match.group(1).upper()}/{int(id_match.group(2))}/{id_match.group(3)}"

    short_rm = re.search(r"\brm[_ -]+(\d+)[_ -]+(\d{2}|20\d{2})\b", folded)
    if short_rm:
        year = normalize_year(short_rm.group(2))
        return f"RM/{int(short_rm.group(1))}/{year}"

    if not ("usneseni" in folded and ("vypis" in folded or "zasedani" in folded or "schuze" in folded)):
        return None

    meeting = re.search(r"(?:ze?|z)\s+(\d+)\.\s+(?:schuze|zasedani)", folded)
    year_match = re.search(r"\b(20\d{2}|19\d{2})\b", folded)
    if not (meeting and year_match):
        return None

    if "zastupitel" in folded or " zml" in folded:
        organ = "ZM"
    else:
        organ = "RM"
    return f"{organ}/{int(meeting.group(1))}/{year_match.group(1)}"


def normalize_year(value: str) -> str:
    if len(value) == 2:
        return f"20{value}"
    return value


def notice_kind(title: str, notice_type: str) -> str | None:
    folded_title = fold_ascii(title).lower()
    folded_type = fold_ascii(notice_type).lower()
    if "rozpoctove opatreni" in folded_title:
        return "budget_change"
    if "vypis" in folded_title and "usneseni" in folded_title:
        return "resolution"
    if "usneseni" in folded_title and ("zasedani" in folded_title or "schuze" in folded_title):
        return "resolution"
    if "vypis z usneseni" in folded_type and "usneseni" in folded_title:
        return "resolution"
    return None


def notice_key(kind: str, title: str, reference: str = "") -> str | None:
    combined = f"{title} {reference}"
    if kind == "budget_change":
        return parse_budget_key(combined)
    if kind == "resolution":
        return parse_resolution_key(combined)
    return None


def parse_notice_board(html: str, page_url: str = NOTICE_BOARD_URL) -> list[Notice]:
    soup = BeautifulSoup(html, "html.parser")
    notices: list[Notice] = []

    for row in soup.select("table.uredni_deska_vypis tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        link = cells[2].find("a", href=True)
        if not link:
            continue

        title = normalize_ws(link.get_text(" ", strip=True))
        notice_type_value = normalize_ws(cells[4].get_text(" ", strip=True))
        kind = notice_kind(title, notice_type_value)
        if not kind:
            continue

        key = notice_key(kind, title, cells[0].get_text(" ", strip=True))
        if not key:
            continue

        notices.append(
            Notice(
                kind=kind,
                key=key,
                title=title,
                detail_url=urljoin(page_url, link["href"]),
                posted=normalize_ws(cells[1].get_text(" ", strip=True)),
                source=normalize_ws(cells[3].get_text(" ", strip=True)),
                notice_type=notice_type_value,
            )
        )

    return notices


def parse_attachments(html: str, detail_url: str) -> list[Attachment]:
    soup = BeautifulSoup(html, "html.parser")
    attachments: list[Attachment] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        absolute = urljoin(detail_url, href)
        parsed = urlparse(absolute)
        title = link.get("title", "")
        label = normalize_ws(link.get_text(" ", strip=True))
        looks_like_pdf = (
            parsed.path.lower().endswith(".pdf")
            or "filemanager/files/file.php" in parsed.path
            or ".pdf" in title.lower()
        )
        if not looks_like_pdf or absolute in seen:
            continue
        seen.add(absolute)
        attachments.append(Attachment(url=absolute, label=label))

    return attachments


def budget_filename(title: str, fallback: str) -> str:
    folded = fold_ascii(title).lower()
    numeric = re.search(
        r"rozpoctove opatreni c\.?\s*(\d{1,4})\s*[/_]\s*(20\d{2}).*?"
        r"dne\s+(\d{1,2})\.\s*(\d{1,2})\.?\s*(20\d{2})",
        folded,
    )
    if numeric:
        number, year, day, month, date_year = numeric.groups()
        return f"rozpoctove_opatreni_c._{int(number)}_{year}_dne_{int(day)}.{int(month)}._{date_year}.pdf"

    match = re.search(
        r"rozpoctove opatreni c\.?\s*(\d{1,4})\s*[/_]\s*(20\d{2}).*?"
        r"dne\s+(\d{1,2})\.?\s*([a-z]+)\s+(20\d{2})",
        folded,
    )
    if match:
        number, year, day, month, date_year = match.groups()
        return f"rozpoctove_opatreni_c._{int(number)}_{year}_dne_{int(day)}._{month}_{date_year}.pdf"
    return slugify_pdf_name(fallback or title)


def target_filename(notice: Notice, attachment: Attachment) -> str:
    if notice.kind == "budget_change":
        return budget_filename(notice.title, attachment.label)
    label = attachment.label
    if label and len(label) <= 80 and parse_resolution_key(label):
        return slugify_pdf_name(label)
    return slugify_pdf_name(notice.title)


def target_dir(notice: Notice, resources_dir: Path, ro_dir: Path) -> Path:
    if notice.kind == "budget_change":
        return ro_dir
    if notice.key.startswith("ZM/"):
        return resources_dir / "zastupitelstvo"
    return resources_dir / "rm"


def iter_json_files(path: Path) -> Iterable[Path]:
    if not path.exists():
        return []
    return path.glob("*.json")


def existing_budget_keys(workdir: Path, ro_dir: Path) -> set[str]:
    keys: set[str] = set()
    for path in iter_json_files(workdir / "rozpoctova-opatreni"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data.get("id"), str):
            keys.add(data["id"])
    for path in ro_dir.glob("*.pdf") if ro_dir.exists() else []:
        key = parse_budget_key(path.name)
        if key:
            keys.add(key)
    return keys


def existing_resolution_keys(workdir: Path, resources_dir: Path) -> set[str]:
    keys: set[str] = set()
    for path in iter_json_files(workdir / "phase1"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        resolution_id = data.get("id")
        if not isinstance(resolution_id, str):
            continue
        parts = resolution_id.split("/")
        if len(parts) != 4 or parts[0] not in {"RM", "ZM"}:
            continue
        try:
            meeting = int(parts[2])
        except ValueError:
            continue
        keys.add(f"{parts[0]}/{meeting}/{parts[3]}")

    for folder in (resources_dir / "rm", resources_dir / "zastupitelstvo"):
        if not folder.exists():
            continue
        for path in folder.glob("*.pdf"):
            key = parse_resolution_key(path.name)
            if key:
                keys.add(key)
    return keys


def existing_keys(workdir: Path, resources_dir: Path, ro_dir: Path) -> dict[str, set[str]]:
    return {
        "budget_change": existing_budget_keys(workdir, ro_dir),
        "resolution": existing_resolution_keys(workdir, resources_dir),
    }


def request_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_text(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if "charset=" not in content_type.lower():
        response.encoding = "utf-8"
    elif not response.encoding:
        response.encoding = "utf-8"
    return response.text


def download_pdf(session: requests.Session, url: str) -> bytes:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    content = response.content
    if not content.lstrip().startswith(b"%PDF"):
        raise ValueError(f"Downloaded attachment is not a PDF: {url}")
    return content


def sync_notices(
    *,
    notice_url: str,
    resources_dir: Path,
    ro_dir: Path,
    workdir: Path,
    dry_run: bool,
) -> list[DownloadedFile]:
    session = request_session()
    notices = parse_notice_board(fetch_text(session, notice_url), notice_url)
    known = existing_keys(workdir, resources_dir, ro_dir)
    downloaded: list[DownloadedFile] = []

    for notice in notices:
        if notice.key in known.get(notice.kind, set()):
            continue

        attachments = parse_attachments(fetch_text(session, notice.detail_url), notice.detail_url)
        pdfs = attachments[:1]
        if not pdfs:
            raise RuntimeError(f"No PDF attachment found for notice: {notice.title} ({notice.detail_url})")

        for attachment in pdfs:
            destination = target_dir(notice, resources_dir, ro_dir) / target_filename(notice, attachment)
            record = DownloadedFile(
                kind=notice.kind,
                key=notice.key,
                title=notice.title,
                detail_url=notice.detail_url,
                pdf_url=attachment.url,
                path=str(destination),
            )
            downloaded.append(record)
            if dry_run:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(download_pdf(session, attachment.url))
            known.setdefault(notice.kind, set()).add(notice.key)

    return downloaded


def write_manifest(path: Path, downloaded: list[DownloadedFile], dry_run: bool) -> None:
    payload = {
        "dry_run": dry_run,
        "found": bool(downloaded),
        "downloaded": [asdict(item) for item in downloaded],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_pr_body(path: Path, manifest_path: Path, downloaded: list[DownloadedFile], dry_run: bool) -> None:
    lines = ["Automated sync from Litovel current public notices.", ""]
    if downloaded:
        lines.append("Would download:" if dry_run else "Downloaded and processed:")
        for item in downloaded:
            lines.append(f"- `{item.path}` (`{item.key}`) from {item.detail_url}")
    else:
        lines.append("No new matching PDFs were found.")
    lines.append("")
    lines.append(f"Source notice board: {NOTICE_BOARD_URL}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_github_output(downloaded: list[DownloadedFile], dry_run: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as fh:
        fh.write(f"found={'true' if downloaded else 'false'}\n")
        fh.write(f"dry_run={'true' if dry_run else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notice-url", default=NOTICE_BOARD_URL)
    parser.add_argument("--resources", type=Path, default=Path("resources"))
    parser.add_argument("--ro-pdf", type=Path, default=Path("resources/rozpoctova-opatreni"))
    parser.add_argument("--workdir", type=Path, default=Path("work"))
    parser.add_argument("--manifest", type=Path, default=Path(".litovel-sync-manifest.json"))
    parser.add_argument("--pr-body", type=Path, default=Path(".litovel-sync-pr-body.md"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    downloaded = sync_notices(
        notice_url=args.notice_url,
        resources_dir=args.resources,
        ro_dir=args.ro_pdf,
        workdir=args.workdir,
        dry_run=args.dry_run,
    )
    write_manifest(args.manifest, downloaded, args.dry_run)
    write_pr_body(args.pr_body, args.manifest, downloaded, args.dry_run)
    write_github_output(downloaded, args.dry_run)

    if downloaded:
        for item in downloaded:
            action = "Would download" if args.dry_run else "Downloaded"
            print(f"{action}: {item.path} ({item.title})")
    else:
        print("No new Litovel resolution or budget-change PDFs found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
