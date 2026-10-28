#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract → Enrich → Export: lokální zpracování usnesení města Litovel.

Extract parsuje PDF usnesení a rozpočtových opatření a doplňuje podporované
archivní záznamy. Enrich analyzuje a klasifikuje celý uložený korpus, resolvuje
reference a propojuje rozpočtová opatření. Export sestaví indexy a roční JSON
z finálních dat a jednou vygeneruje stránky a sitemap.

GitHub Actions parsuje pouze PDF vybraná svým manifestem pomocí samostatných
parserů a pak spouští Enrich → Export. Publikování přes pull requesty zůstává
v Actions. Historické názvy skriptů a work/phase1, phase3, phase4 se nemění.

Model se načítá přes --classifier-url a --classifier-sha256; cache je určena
--classifier-cache. Kategorie pochází přímo z modelu, bez ručních oprav.
Export zachovává classification a přidává české názvy témat pro web.

Použití:
  python pipeline.py --pdf resources
  python pipeline.py --from-stage enrich --to-stage export
  python pipeline.py --from-stage export
  python pipeline.py --pdf resources --to-stage extract
  python pipeline.py --pdf resources --without-budget
  python pipeline.py --pdf resources --dry-run

--without-budget nepoužívá stará propojená data ani automaticky nalezená RO.
Existující exportované soubory se nemažou; pro samostatný export bez RO použijte
nový --export adresář. --dry-run nevytváří adresáře a nespouští příkazy.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from resolution_classification import DEFAULT_SHA256, DEFAULT_URL

STAGES = ("extract", "enrich", "export")


def info(message):
    print(f"   {message}", flush=True)


def run_operation(name, command):
    """Run one existing operation script, propagating nonzero exit status."""
    info(f"Příkaz: {' '.join(str(part) for part in command)}")
    started = time.monotonic()
    result = subprocess.run(command, text=True)
    if result.returncode:
        info(f"✖ {name} selhala (kód {result.returncode})")
        return False
    info(f"✔ {name} dokončena za {time.monotonic() - started:.1f} s")
    return True


def collect_pdf_dirs(root, exclude=None):
    """Read PDF directories recursively, excluding the budget source tree."""
    excluded = [path.resolve() for path in (exclude or [])]
    directories = []
    for directory in [root, *sorted(path for path in root.rglob("*") if path.is_dir())]:
        resolved = directory.resolve()
        if any(resolved.is_relative_to(path) for path in excluded):
            continue
        if any(directory.glob("*.pdf")):
            directories.append(directory)
    return directories


def default_archive_roots(workdir):
    return [path for path in (workdir / "archive_rm", workdir / "archive_zm") if path.exists()]


def output_exists(path, kind):
    if kind == "json_dir":
        return path.is_dir() and any(path.glob("*.json"))
    if kind == "dir":
        return path.is_dir()
    return path.is_file()


def operation(name, command, *outputs, recursive_pdf=False):
    return {"name": name, "command": command, "outputs": outputs, "recursive_pdf": recursive_pdf}


def build_stages(pdf_dir, ro_pdf_dir, workdir, export_dir, terms=None,
                 classifier_url=DEFAULT_URL, classifier_sha256=DEFAULT_SHA256,
                 classifier_cache=Path(".cache/resolution-classifier"), without_budget=False,
                 incremental_classification=False):
    """Group existing scripts under three stages; keep their storage contracts.

    Both export consumers read the same final resolution dataset. Building this
    description performs no filesystem mutations or model loading.
    """
    raw = workdir / "phase1"
    analyzed = workdir / "phase3"
    resolved = workdir / "phase4"
    budget = workdir / "rozpoctova-opatreni"
    linked = workdir / "rozpoctova-opatreni-linked"
    index = export_dir / "assets/usneseni"
    final_resolutions = (resolved if without_budget else linked) / "usneseni.json"

    extract = [operation("Parsování PDF usnesení a doplnění archivu", None,
                         (raw, "json_dir"), recursive_pdf=True)]
    if not without_budget:
        extract.append(operation("Parsování rozpočtových opatření",
                                 [sys.executable, "parse_rozpoctova_opatreni.py", str(ro_pdf_dir), str(budget)],
                                 (budget, "json_dir")))

    enrich = [
        operation("Analýza a tematická klasifikace",
                  [sys.executable, "phase2_resolution_analysis.py", "--input", str(raw),
                   "--output", str(analyzed), "--classifier-url", classifier_url,
                   "--classifier-sha256", classifier_sha256, "--classifier-cache", str(classifier_cache),
                   "--classification-output", str(workdir / "classifier")]
                  + (["--incremental-classification"] if incremental_classification else []),
                  (analyzed, "json_dir")),
        operation("Resolvování referencí a volebních období",
                  [sys.executable, "phase3_resolve_references.py", "--input", str(analyzed),
                   "--output", str(resolved)] + (["--terms", str(terms)] if terms else []),
                  (resolved / "usneseni.json", "file")),
    ]
    if not without_budget:
        enrich.append(operation("Propojení rozpočtových opatření",
                                [sys.executable, "crosslink_rozpoctova_opatreni.py",
                                 "--resolutions", str(resolved / "usneseni.json"),
                                 "--opatreni", str(budget), "--output", str(linked)],
                                (linked / "usneseni.json", "file"),
                                (linked / "budget_change_index.json", "file"),
                                (linked / "stats.json", "file"),
                                (linked / "rozpoctova-opatreni", "json_dir")))

    export = [operation("Index usnesení a roční JSON data",
                        [sys.executable, "phase4_index_build.py", "--input", str(final_resolutions),
                         "--output", str(index)], (index / "meta.json", "file"))]
    if not without_budget:
        export.append(operation("Index rozpočtových opatření",
                                [sys.executable, "phase4_ro_index_build.py", "--input",
                                 str(linked / "rozpoctova-opatreni"), "--output", str(index / "ro")],
                                (index / "ro/meta.json", "file")))
    render = [sys.executable, "phase5_static_export.py", "--input", str(final_resolutions),
              "--output", str(export_dir)]
    render += (["--without-budget"] if without_budget else
               ["--opatreni", str(linked / "rozpoctova-opatreni")])
    page_outputs = [(export_dir / "usneseni", "dir"), (export_dir / "sitemap-usneseni.xml", "file")]
    if not without_budget:
        page_outputs.append((export_dir / "rozpoctova-opatreni/index.html", "file"))
    export.append(operation("Statické stránky a sitemap", render, *page_outputs))
    return [{"name": "extract", "operations": extract}, {"name": "enrich", "operations": enrich},
            {"name": "export", "operations": export}]


def validate_inputs(stage, args, previous):
    """Validate only selected-stage inputs, allowing planned dry-run outputs."""
    if stage == "extract":
        if args.pdf is None or not args.pdf.is_dir():
            raise ValueError("Extract vyžaduje --pdf s existujícím adresářem")
        if not collect_pdf_dirs(args.pdf, exclude=[args.ro_pdf]):
            raise ValueError(f"Žádné PDF usnesení nenalezeny: {args.pdf}")
        if not args.without_budget and (not args.ro_pdf.is_dir() or not any(args.ro_pdf.glob("*.pdf"))):
            raise ValueError(f"Chybí PDF rozpočtových opatření: {args.ro_pdf}; použijte --without-budget")
    elif stage == "enrich":
        if args.terms and not args.terms.is_file():
            raise ValueError(f"Soubor volebních období neexistuje: {args.terms}")
        if not (args.dry_run and "extract" in previous):
            require_output(args.workdir / "phase1", "json_dir")
            if not args.without_budget:
                require_output(args.workdir / "rozpoctova-opatreni", "json_dir")
    elif not (args.dry_run and "enrich" in previous):
        source = args.workdir / ("phase4" if args.without_budget else "rozpoctova-opatreni-linked")
        require_output(source / "usneseni.json", "file")
        if not args.without_budget:
            require_output(source / "rozpoctova-opatreni", "json_dir")


def require_output(path, kind):
    if not output_exists(path, kind):
        raise ValueError(f"Chybí požadovaná data: {path}")


def run_extraction(args):
    """Reuse recursive resolution parsing and archive promotion, without cleanup."""
    for directory in collect_pdf_dirs(args.pdf, exclude=[args.ro_pdf]):
        command = [sys.executable, "phase1_parse_pdf.py", str(directory), str(args.workdir / "phase1")]
        if args.dry_run:
            info("DRY RUN: " + " ".join(command))
        elif not run_operation("Parsování PDF usnesení", command):
            return False
    if not args.no_archive_current:
        roots = args.archive_roots or default_archive_roots(args.workdir)
        roots = [root for root in roots if root.exists()]
        if roots:
            command = [sys.executable, "tools/archive_promote_current.py", "--output", str(args.workdir / "phase1"),
                       "--report", str(args.workdir / "archive_current_promoted.json")]
            for root in roots:
                command.extend(["--archive-root", str(root)])
            if args.dry_run:
                info("DRY RUN: " + " ".join(command))
            elif not run_operation("Doplnění archivních usnesení", command):
                return False
    return True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Extract → Enrich → Export: usnesení města Litovel",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--pdf", type=Path, metavar="DIR", help="PDF usnesení; povinné pouze pro Extract")
    parser.add_argument("--ro-pdf", type=Path, default=Path("resources/rozpoctova-opatreni"), metavar="DIR")
    parser.add_argument("--workdir", type=Path, default=Path("work"), metavar="DIR")
    parser.add_argument("--export", type=Path, default=Path("export"), metavar="DIR")
    parser.add_argument("--from-stage", choices=STAGES, default="extract", help="Výchozí: extract")
    parser.add_argument("--to-stage", choices=STAGES, default="export", help="Výchozí: export")
    parser.add_argument("--without-budget", action="store_true", help="Zpracovat usnesení bez rozpočtových opatření")
    parser.add_argument("--dry-run", action="store_true", help="Zobrazit příkazy bez spuštění a zápisů")
    parser.add_argument("--archive-root", type=Path, action="append", dest="archive_roots")
    parser.add_argument("--no-archive-current", action="store_true")
    parser.add_argument("--terms", type=Path, help="JSON volebních období pro Enrich")
    parser.add_argument("--classifier-url", default=DEFAULT_URL, help="URL versionovaného modelu")
    parser.add_argument("--classifier-sha256", default=DEFAULT_SHA256, help="Očekávaný SHA-256 archivu modelu")
    parser.add_argument("--classifier-cache", type=Path, default=Path(".cache/resolution-classifier"))
    parser.add_argument("--incremental-classification", action="store_true",
                        help="Přepočítat pouze nová nebo změněná usnesení")
    args = parser.parse_args(argv)
    if STAGES.index(args.from_stage) > STAGES.index(args.to_stage):
        parser.error("--from-stage nesmí následovat po --to-stage")
    return args


def main(argv=None):
    args = parse_args(argv)
    stages = build_stages(args.pdf, args.ro_pdf, args.workdir, args.export, args.terms,
                          args.classifier_url, args.classifier_sha256, args.classifier_cache,
                          args.without_budget, args.incremental_classification)
    selected = stages[STAGES.index(args.from_stage):STAGES.index(args.to_stage) + 1]
    print(f"Pipeline: {args.from_stage} → {args.to_stage}", flush=True)
    started = time.monotonic()
    previous = []
    for stage in selected:
        print(f"\n=== {stage['name'].capitalize()} ===", flush=True)
        try:
            validate_inputs(stage["name"], args, previous)
            for step in stage["operations"]:
                info(step["name"])
                if step["recursive_pdf"]:
                    ok = run_extraction(args)
                elif args.dry_run:
                    info("DRY RUN: " + " ".join(step["command"]))
                    ok = True
                else:
                    ok = run_operation(step["name"], step["command"])
                if not ok:
                    raise ValueError(f"Operace selhala: {step['name']}")
                if not args.dry_run:
                    for path, kind in step["outputs"]:
                        try:
                            require_output(path, kind)
                        except ValueError as error:
                            raise ValueError(f"{step['name']}: {error}") from error
        except (ValueError, OSError) as error:
            info(f"✖ {stage['name']}: {error}")
            return 1
        previous.append(stage["name"])
    info(f"✔ {'Dry run' if args.dry_run else 'Pipeline'} dokončen za {time.monotonic() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
