#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Pipeline – spustí všechny fáze zpracování usnesení za sebou.

Fáze 3 analyzuje text a klasifikuje usnesení finálním tematickým modelem.
Modelový balíček se načítá z --classifier-url a ověřuje přes --classifier-sha256.
Výchozí je GitHub Release v1.0.0; jiný checkout není potřeba. Stažené váhy se
uchovávají v --classifier-cache a další běhy používají lokální cache.
Ruční opravy mají přednost před predikcí. Nejednoznačné případy mají kategorii
null a stav manual_review_required. Objekt classification se zachovává v
navazujících fázích a ročních JSON datech statického exportu.

Výchozí adresářová struktura (lze přepsat argumenty):
  pdf_dir/          ← vstupní PDF soubory pro usnesení
  work/phase1/      ← výstup fáze 1
  work/phase3/      ← výstup fáze 3
  work/phase4/      ← výstup fáze 4
  work/classifier/  ← predikce modelu, ruční rozhodnutí a fronta pro kontrolu
  .cache/resolution-classifier/ ← ověřené modelové balíčky (také cache v Actions)
  work/rozpoctova-opatreni/        ← výstup fáze 2
  work/rozpoctova-opatreni-linked/ ← výstup fáze 7
  export/assets/usneseni/    ← výstup fáze 5
  export/assets/usneseni/ro/ ← výstup fáze 8
  export/                    ← výstup fáze 6 a 9 (statický export)

Použití:
  # Celý pipeline od začátku
  python pipeline.py --pdf pdf_dir/

  # Klasifikovat již extrahovaná usnesení a přegenerovat celý export
  python pipeline.py --from-phase 3 --to-phase 9

  # Jiný versionovaný modelový balíček a jeho checksum
  python pipeline.py --from-phase 3 --classifier-url MODEL_URL --classifier-sha256 SHA256

  # Spustit pouze parsování RO a analýzu usnesení nad existující fází 1
  python pipeline.py --pdf pdf_dir/ --from-phase 2 --to-phase 3

  # Vlastní pracovní adresář
  python pipeline.py --pdf pdf_dir/ --workdir moje_data/ --export vystup/

  # Naparsovat rozpočtová opatření a propojit je s usneseními
  python pipeline.py --from-phase 2 --to-phase 7

  # Vzít už naparsovaná data a přegenerovat vše od crosslinku dál
  python pipeline.py --from-phase 7 --to-phase 9
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from resolution_classification import DEFAULT_SHA256, DEFAULT_URL


# ──────────────────────────────────────────────
# Barvy pro terminál (degradují na prázdné stringy pokud není TTY)
# ──────────────────────────────────────────────

def _supports_color():
    import os
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and os.name != "nt"

if _supports_color():
    BOLD  = "\033[1m"
    GREEN = "\033[32m"
    RED   = "\033[31m"
    CYAN  = "\033[36m"
    DIM   = "\033[2m"
    RESET = "\033[0m"
else:
    BOLD = GREEN = RED = CYAN = DIM = RESET = ""


# ──────────────────────────────────────────────
# Pomocné funkce
# ──────────────────────────────────────────────

def header(text: str):
    print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}{text}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")


def success(text: str):
    print(f"{GREEN}✔  {text}{RESET}")


def failure(text: str):
    print(f"{RED}✖  {text}{RESET}")


def info(text: str):
    print(f"{DIM}   {text}{RESET}")


def run_phase(name: str, cmd: list[str]) -> bool:
    """Spustí příkaz a vrátí True při úspěchu."""
    info(f"Příkaz: {' '.join(str(c) for c in cmd)}")
    t0 = time.monotonic()
    result = subprocess.run(cmd, text=True)
    elapsed = time.monotonic() - t0

    if result.returncode == 0:
        success(f"{name} dokončena za {elapsed:.1f} s")
        return True
    else:
        failure(f"{name} selhala (kód {result.returncode})")
        return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def collect_pdf_dirs(root: Path, exclude: list[Path] | None = None) -> list[Path]:
    """
    Rekurzivně projde root a vrátí seznam adresářů, které přímo obsahují
    alespoň jeden *.pdf soubor. Zahrnuje i samotný root.
    """
    exclude_resolved = [p.resolve() for p in (exclude or [])]
    dirs = []
    for d in sorted(root.rglob("*")):
        d_resolved = d.resolve()
        if any(_is_relative_to(d_resolved, e) for e in exclude_resolved):
            continue
        if d.is_dir() and any(d.glob("*.pdf")):
            dirs.append(d)
    # také root sám, pokud obsahuje PDF přímo
    root_resolved = root.resolve()
    if (
        not any(_is_relative_to(root_resolved, e) for e in exclude_resolved)
        and any(root.glob("*.pdf"))
        and root not in dirs
    ):
        dirs.insert(0, root)
    return dirs


def run_phase1_recursive(
    pdf_dir: Path,
    phase1: Path,
    dry_run: bool,
    exclude: list[Path] | None = None,
) -> bool:
    """
    Spustí phase1_parse_pdf.py pro každý podadresář (i root), který obsahuje PDF.
    Všechny výstupy jdou do stejného phase1/ adresáře.
    """
    dirs = collect_pdf_dirs(pdf_dir, exclude=exclude)

    if not dirs:
        failure(f"Žádné PDF soubory nenalezeny v {pdf_dir} ani jejích podadresářích")
        return False

    info(f"Nalezeno {len(dirs)} adresář(ů) s PDF soubory")
    phase1.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    for d in dirs:
        count = len(list(d.glob("*.pdf")))
        info(f"  {d}  ({count} PDF)")
        cmd = [sys.executable, "phase1_parse_pdf.py", str(d), str(phase1)]
        if dry_run:
            info("DRY RUN: " + " ".join(str(c) for c in cmd))
            continue
        result = subprocess.run(cmd, text=True)
        if result.returncode != 0:
            failure(f"Fáze 1 selhala pro adresář: {d}")
            return False

    elapsed = time.monotonic() - t0
    if not dry_run:
        success(f"Fáze 1 – parsování PDF dokončeno za {elapsed:.1f} s")
    return True


def default_archive_roots(workdir: Path) -> list[Path]:
    return [
        root
        for root in (workdir / "archive_rm", workdir / "archive_zm")
        if root.exists()
    ]


def run_archive_current_promotion(
    archive_roots: list[Path],
    phase1: Path,
    workdir: Path,
    dry_run: bool,
) -> bool:
    roots = [root for root in archive_roots if root.exists()]
    if not roots:
        info("Žádné archivní zdroje pro promotion do současných usnesení")
        return True

    cmd = [
        sys.executable,
        "tools/archive_promote_current.py",
        "--output",
        str(phase1),
        "--report",
        str(workdir / "archive_current_promoted.json"),
    ]
    for root in roots:
        cmd.extend(["--archive-root", str(root)])

    if dry_run:
        info("DRY RUN: " + " ".join(str(c) for c in cmd))
        return True

    return run_phase("Archivní usnesení ve formátu současné pipeline", cmd)


# ──────────────────────────────────────────────
# Definice fází
# ──────────────────────────────────────────────

def build_phases(
    pdf_dir: Path,
    ro_pdf_dir: Path,
    workdir: Path,
    export_dir: Path,
    terms: Path | None = None,
    classifier_url: str = DEFAULT_URL,
    classifier_sha256: str = DEFAULT_SHA256,
    classifier_cache: Path = Path(".cache/resolution-classifier"),
) -> list[dict]:
    """
    Vrátí seznam fází. Každá fáze je slovník:
      number  – číslo fáze (int)
      name    – popis
      cmd     – callable() -> list[str] (příkaz fáze)
      output_check – callable() -> bool (ověří existenci výstupu)

    Fáze 3 předává URL, SHA-256 a cache lokálnímu inferenčnímu modulu.
    Čísla fází 1–9 se při přidání klasifikace nemění.
    """

    phase1 = workdir / "phase1"
    ro = workdir / "rozpoctova-opatreni"
    phase3 = workdir / "phase3"
    phase4 = workdir / "phase4"
    ro_linked = workdir / "rozpoctova-opatreni-linked"
    exported_usneseni_index = export_dir / "assets" / "usneseni"
    exported_ro_index = exported_usneseni_index / "ro"

    return [
        {
            "number": 1,
            "name": "Fáze 1 – parsování PDF (rekurzivní)",
            "recursive_phase1": True,
            "output_check": lambda: phase1.exists() and any(phase1.glob("*.json")),
            "output_hint": str(phase1),
        },
        {
            "number": 2,
            "name": "Fáze 2 – parsování rozpočtových opatření",
            "cmd": lambda: [
                sys.executable, "parse_rozpoctova_opatreni.py",
                str(ro_pdf_dir),
                str(ro),
            ],
            "output_check": lambda: ro.exists() and any(ro.glob("*.json")),
            "output_hint": str(ro),
            "requires_ro_pdf": True,
        },
        {
            "number": 3,
            "name": "Fáze 3 – analýza a tematická klasifikace usnesení",
            "cmd": lambda: [
                sys.executable, "phase2_resolution_analysis.py",
                "--input", str(phase1),
                "--output", str(phase3),
                "--classifier-url", classifier_url,
                "--classifier-sha256", classifier_sha256,
                "--classifier-cache", str(classifier_cache),
                "--classification-output", str(workdir / "classifier"),
            ],
            "output_check": lambda: phase3.exists() and any(phase3.glob("*.json")),
            "output_hint": str(phase3),
        },
        {
            "number": 4,
            "name": "Fáze 4 – resolvování referencí",
            "cmd": lambda: [
                sys.executable, "phase3_resolve_references.py",
                "--input", str(phase3),
                "--output", str(phase4),
            ] + (["--terms", str(terms)] if terms else []),
            "output_check": lambda: (phase4 / "usneseni.json").exists(),
            "output_hint": str(phase4 / "usneseni.json"),
        },
        {
            "number": 5,
            "name": "Fáze 5 – sestavení indexu usnesení",
            "cmd": lambda: [
                sys.executable, "phase4_index_build.py",
                "--input", str(phase4 / "usneseni.json"),
                "--output", str(exported_usneseni_index),
            ],
            "output_check": lambda: (exported_usneseni_index / "meta.json").exists(),
            "output_hint": str(exported_usneseni_index),
        },
        {
            "number": 6,
            "name": "Fáze 6 – export webu bez rozpočtových opatření",
            "cmd": lambda: [
                sys.executable, "phase5_static_export.py",
                "--input", str(phase4 / "usneseni.json"),
                "--output", str(export_dir),
            ],
            "output_check": lambda: export_dir.exists() and any(export_dir.iterdir()),
            "output_hint": str(export_dir),
        },
        {
            "number": 7,
            "name": "Fáze 7 – propojení rozpočtových opatření s usneseními",
            "cmd": lambda: [
                sys.executable, "crosslink_rozpoctova_opatreni.py",
                "--resolutions", str(phase4 / "usneseni.json"),
                "--opatreni", str(ro),
                "--output", str(ro_linked),
            ],
            "output_check": lambda: (
                (ro_linked / "usneseni.json").exists()
                and (ro_linked / "budget_change_index.json").exists()
                and (ro_linked / "stats.json").exists()
                and (ro_linked / "rozpoctova-opatreni").exists()
            ),
            "output_hint": str(ro_linked),
        },
        {
            "number": 8,
            "name": "Fáze 8 – sestavení indexu rozpočtových opatření",
            "cmd": lambda: [
                sys.executable, "phase4_ro_index_build.py",
                "--input", str(ro_linked / "rozpoctova-opatreni"),
                "--output", str(exported_ro_index),
            ],
            "output_check": lambda: (exported_ro_index / "meta.json").exists(),
            "output_hint": str(exported_ro_index),
        },
        {
            "number": 9,
            "name": "Fáze 9 – export webu včetně rozpočtových opatření",
            "cmd": lambda: [
                sys.executable, "phase5_static_export.py",
                "--input", str(ro_linked / "usneseni.json"),
                "--opatreni", str(ro_linked / "rozpoctova-opatreni"),
                "--output", str(export_dir),
            ],
            "output_check": lambda: (
                (export_dir / "usneseni").exists()
                and (export_dir / "rozpoctova-opatreni" / "index.html").exists()
            ),
            "output_hint": str(export_dir),
        },
    ]


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Pipeline pro zpracování usnesení města Litovel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--pdf", type=Path, metavar="DIR",
        help="Adresář se vstupními PDF soubory usnesení (povinný jen při spuštění fáze 1)"
    )
    ap.add_argument(
        "--ro-pdf", type=Path, default=Path("resources/rozpoctova-opatreni"), metavar="DIR",
        help="Adresář s PDF rozpočtových opatření (výchozí: resources/rozpoctova-opatreni)"
    )
    ap.add_argument(
        "--workdir", type=Path, default=Path("work"), metavar="DIR",
        help="Pracovní adresář pro meziproduktová data (výchozí: work/)"
    )
    ap.add_argument(
        "--export", type=Path, default=Path("export"), metavar="DIR",
        help="Cílový adresář statického exportu (výchozí: export/)"
    )
    ap.add_argument(
        "--from-phase", type=int, default=1, metavar="N",
        help="Začít od fáze N (výchozí: 1)"
    )
    ap.add_argument(
        "--to-phase", type=int, default=6, metavar="N",
        help="Skončit po fázi N (výchozí: 6; fáze 7–9 doplňují rozpočtová opatření)"
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Pouze zobraz příkazy, nespouštěj je"
    )
    ap.add_argument(
        "--archive-root",
        type=Path,
        action="append",
        dest="archive_roots",
        help="Archivní pracovní adresář pro promotion současného formátu. Lze opakovat.",
    )
    ap.add_argument(
        "--no-archive-current",
        action="store_true",
        help="Nepřidávat moderně strukturovaná archivní usnesení do současné pipeline.",
    )
    ap.add_argument(
        "--terms",
        type=Path,
        help="Volitelný JSON se seznamem volebních období pro fázi resolvování referencí.",
    )
    ap.add_argument(
        "--classifier-url", default=DEFAULT_URL,
        help="URL versionovaného modelového balíčku (výchozí: finální release v1.0.0).",
    )
    ap.add_argument(
        "--classifier-sha256", default=DEFAULT_SHA256,
        help="Očekávaný SHA-256 modelového balíčku (výchozí: finální release v1.0.0).",
    )
    ap.add_argument(
        "--classifier-cache", type=Path, default=Path(".cache/resolution-classifier"),
        help="Lokální cache modelových balíčků; vhodná i pro actions/cache.",
    )
    args = ap.parse_args()

    if not (1 <= args.from_phase <= 9 and 1 <= args.to_phase <= 9):
        failure("--from-phase a --to-phase musí být v rozmezí 1–9")
        sys.exit(1)

    if args.from_phase > args.to_phase:
        failure("--from-phase nesmí být větší než --to-phase")
        sys.exit(1)

    if args.from_phase <= 1 <= args.to_phase:
        if args.pdf is None:
            failure("--pdf je povinný při spuštění fáze 1")
            sys.exit(1)
        if not args.pdf.exists():
            failure(f"Adresář s PDF neexistuje: {args.pdf}")
            sys.exit(1)

    if args.terms and not args.terms.exists():
        failure(f"Soubor volebních období neexistuje: {args.terms}")
        sys.exit(1)

    phases = build_phases(args.pdf, args.ro_pdf, args.workdir, args.export, args.terms,
                          args.classifier_url, args.classifier_sha256, args.classifier_cache)
    selected = [p for p in phases if args.from_phase <= p["number"] <= args.to_phase]

    if any(p.get("requires_ro_pdf") for p in selected) and not args.ro_pdf.exists():
        failure(f"Adresář s PDF rozpočtových opatření neexistuje: {args.ro_pdf}")
        sys.exit(1)

    print(f"\n{BOLD}Pipeline usnesení města Litovel{RESET}")
    if args.pdf is not None:
        print(f"  PDF vstup : {args.pdf}")
    if any(p.get("requires_ro_pdf") for p in selected):
        print(f"  RO PDF    : {args.ro_pdf}")
    print(f"  Pracovní  : {args.workdir}")
    print(f"  Export    : {args.export}")
    print(f"  Fáze      : {args.from_phase} – {args.to_phase}")
    if args.dry_run:
        print(f"  {RED}DRY RUN – příkazy se nespustí{RESET}")

    t_total = time.monotonic()
    failed_phases = []

    for phase in selected:
        header(phase["name"])

        if phase.get("recursive_phase1"):
            ok = run_phase1_recursive(
                args.pdf,
                args.workdir / "phase1",
                args.dry_run,
                exclude=[args.ro_pdf],
            )
            if ok and not args.no_archive_current:
                archive_roots = args.archive_roots or default_archive_roots(args.workdir)
                ok = run_archive_current_promotion(
                    archive_roots,
                    args.workdir / "phase1",
                    args.workdir,
                    args.dry_run,
                )
        else:
            cmd = phase["cmd"]()
            if args.dry_run:
                info("DRY RUN: " + " ".join(str(c) for c in cmd))
                ok = True
            else:
                ok = run_phase(phase["name"], cmd)

        if not ok:
            failed_phases.append(phase["number"])
            failure(f"Pipeline přerušen na fázi {phase['number']}.")
            sys.exit(1)

        if not args.dry_run:
            if phase["output_check"]():
                info(f"Výstup ověřen: {phase['output_hint']}")
            else:
                failure(f"Výstup nebyl nalezen: {phase['output_hint']}")
                failed_phases.append(phase["number"])
                sys.exit(1)

    elapsed_total = time.monotonic() - t_total

    if args.dry_run:
        print(f"\n{BOLD}Dry run dokončen.{RESET}\n")
    else:
        print(f"\n{BOLD}{GREEN}{'═' * 60}{RESET}")
        print(f"{BOLD}{GREEN}  ✔  Všechny fáze dokončeny za {elapsed_total:.1f} s{RESET}")
        print(f"{BOLD}{GREEN}{'═' * 60}{RESET}\n")


if __name__ == "__main__":
    main()
