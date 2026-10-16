"""The command line. Seven verbs, no daemon, no login."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from ledgerlocal import __version__, export, offline
from ledgerlocal import config as config_module
from ledgerlocal.categorize import EXAMPLE_RULES, Ruleset
from ledgerlocal.config import EXAMPLE_CONFIG, Config, config_home
from ledgerlocal.errors import LedgerLocalError
from ledgerlocal.ingest import ingest, recategorise
from ledgerlocal.providers import build_provider
from ledgerlocal.store import Store, totals_by

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 1

    try:
        config = _resolve_config(args)
    except LedgerLocalError as exc:
        print(f"{RED}config error:{RESET} {exc}", file=sys.stderr)
        return 2

    if config.enforce_offline and not getattr(args, "no_offline_guard", False):
        offline.enforce(config.allow_hosts)

    try:
        return args.handler(args, config)
    except LedgerLocalError as exc:
        print(f"{RED}error:{RESET} {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


# ---------------------------------------------------------------- parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledgerlocal",
        description="Sort invoices and receipts with an open-weight model on your own machine.",
    )
    parser.add_argument("--version", action="version", version=f"ledgerlocal {__version__}")
    parser.add_argument("--config", type=Path, help="path to config.toml")
    parser.add_argument("--library", type=Path, help="override the library directory")
    parser.add_argument("--provider", help="ollama | openai-compatible | fake")
    parser.add_argument("--host", help="local inference server, e.g. http://127.0.0.1:11434")
    parser.add_argument("--vision-model", dest="vision_model")
    parser.add_argument("--text-model", dest="text_model")
    parser.add_argument(
        "--no-offline-guard",
        action="store_true",
        help="disable the socket allowlist (you should not need this)",
    )

    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="check the local model runtime is ready")
    doctor.set_defaults(handler=_cmd_doctor)

    init = sub.add_parser("init", help="write a starter config.toml and rules.toml")
    init.add_argument("--force", action="store_true")
    init.set_defaults(handler=_cmd_init)

    ing = sub.add_parser("ingest", help="read documents and file them")
    ing.add_argument("paths", nargs="+", type=Path)
    ing.add_argument("--move", action="store_true", help="move originals instead of copying")
    ing.add_argument("--no-file", action="store_true", help="record only, leave files in place")
    ing.add_argument("--reprocess", action="store_true", help="re-read documents already stored")
    ing.add_argument("--no-recursive", action="store_true")
    ing.set_defaults(handler=_cmd_ingest)

    lst = sub.add_parser("list", help="list stored documents")
    _add_filters(lst)
    lst.add_argument("--json", action="store_true")
    lst.set_defaults(handler=_cmd_list)

    review = sub.add_parser("review", help="show only documents the pipeline flagged")
    _add_filters(review)
    review.set_defaults(handler=_cmd_review)

    exp = sub.add_parser("export", help="write CSV / summary files for your accountant")
    _add_filters(exp)
    exp.add_argument("--out", type=Path, help="output directory (default: <library>/exports)")
    exp.add_argument(
        "--format",
        default="all",
        choices=["all", "csv", "summary-csv", "markdown"],
    )
    exp.set_defaults(handler=_cmd_export)

    stats = sub.add_parser("stats", help="totals by category, client and period")
    _add_filters(stats)
    stats.add_argument("--by", default="category", choices=["category", "client", "vendor", "period"])
    stats.set_defaults(handler=_cmd_stats)

    recat = sub.add_parser("recategorise", aliases=["recategorize"], help="replay your rules, no model needed")
    recat.set_defaults(handler=_cmd_recategorise)

    show = sub.add_parser("show", help="print everything stored for one document")
    show.add_argument("digest", help="full or partial document hash")
    show.set_defaults(handler=_cmd_show)

    return parser


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--period", default="", help="2026 or 2026-Q1")
    parser.add_argument("--vendor", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--client", default="")


def _resolve_config(args: argparse.Namespace) -> Config:
    config = config_module.load(args.config)
    overrides = {
        key: value
        for key, value in (
            ("library", args.library),
            ("provider", args.provider),
            ("host", args.host),
            ("vision_model", args.vision_model),
            ("text_model", args.text_model),
        )
        if value
    }
    return replace(config, **overrides) if overrides else config


def _filters(args: argparse.Namespace) -> dict:
    return {
        "period": getattr(args, "period", ""),
        "vendor": getattr(args, "vendor", ""),
        "category": getattr(args, "category", ""),
        "client": getattr(args, "client", ""),
    }


# -------------------------------------------------------------- commands


def _cmd_doctor(args: argparse.Namespace, config: Config) -> int:
    print(f"ledgerlocal {__version__}")
    print(f"  config      {args.config or config_home() / config_module.DEFAULT_CONFIG_NAME}")
    print(f"  library     {config.library}")
    print(f"  database    {config.database}")
    guard = "on (loopback only)" if offline.is_enforced() else "OFF"
    print(f"  egress      {guard}")
    if config.allow_hosts:
        print(f"  allowed     {', '.join(config.allow_hosts)}")

    provider = build_provider(config)
    health = provider.health()
    print(f"  provider    {health.get('provider')} at {health.get('host', 'n/a')}")

    if not health.get("reachable"):
        print(f"\n{RED}The local model runtime is not answering.{RESET}")
        print(f"  {health.get('error', '')}")
        print("\n  Fix: install Ollama from https://ollama.com, then run:")
        print("      ollama serve")
        print(f"      ollama pull {config.vision_model}")
        print(f"      ollama pull {config.text_model}")
        return 1

    models = health.get("models", [])
    print(f"  models      {len(models)} available locally")
    missing = []
    for label, wanted, present in (
        ("vision", config.vision_model, health.get("vision_model_present", True)),
        ("text", config.text_model, health.get("text_model_present", True)),
    ):
        mark = f"{GREEN}ok{RESET}" if present else f"{YELLOW}missing{RESET}"
        print(f"  {label:<11} {wanted} [{mark}]")
        if not present:
            missing.append(wanted)

    if missing:
        print(f"\n{YELLOW}Pull the missing models first:{RESET}")
        for model in missing:
            print(f"      ollama pull {model}")
        return 1

    print(f"\n{GREEN}Ready.{RESET} Try: ledgerlocal ingest ~/Downloads/receipts")
    return 0


def _cmd_init(args: argparse.Namespace, config: Config) -> int:
    home = config_home()
    home.mkdir(parents=True, exist_ok=True)
    for path, content in (
        (home / config_module.DEFAULT_CONFIG_NAME, EXAMPLE_CONFIG),
        (home / "rules.toml", EXAMPLE_RULES),
    ):
        if path.exists() and not args.force:
            print(f"{DIM}kept{RESET}    {path} (use --force to overwrite)")
            continue
        path.write_text(content, "utf-8")
        print(f"{GREEN}wrote{RESET}   {path}")
    config.library.mkdir(parents=True, exist_ok=True)
    print(f"{GREEN}ready{RESET}   {config.library}")
    return 0


def _cmd_ingest(args: argparse.Namespace, config: Config) -> int:
    provider = build_provider(config)
    rules = Ruleset.load(config.rules_path)

    def progress(status: str, path: Path, detail: str | None) -> None:
        marks = {"ingested": f"{GREEN}read{RESET}", "skipped": f"{DIM}seen{RESET}", "failed": f"{RED}fail{RESET}"}
        line = f"  {marks.get(status, status):<16} {path.name}"
        print(line if not detail else f"{line}\n      {DIM}{detail}{RESET}")

    with Store(config.database) as store:
        report = ingest(
            args.paths,
            config=config,
            provider=provider,
            store=store,
            rules=rules,
            file_documents=not args.no_file,
            move=args.move,
            reprocess=args.reprocess,
            recursive=not args.no_recursive,
            progress=progress,
        )

        print()
        for outcome in report.ingested:
            extraction = outcome.result.extraction  # type: ignore[union-attr]
            amount = "?" if extraction.total is None else f"{extraction.total} {extraction.currency}"
            flag = f"  {YELLOW}review{RESET}" if extraction.needs_review else ""
            # A date object formatted with "<10" is handed to strftime, which
            # happily returns the literal "<10". Stringify first.
            when = extraction.issue_date.isoformat() if extraction.issue_date else "undated"
            print(
                f"  {when:<10}  {extraction.vendor[:28]:<28}"
                f"  {amount:>14}  {extraction.category}{flag}"
            )

        print(
            f"\n{len(report.ingested)} ingested, {len(report.skipped)} already known, "
            f"{len(report.failed)} failed, {len(report.needs_review)} need review"
        )
        if report.failed:
            print(f"\n{RED}Failures:{RESET}")
            for outcome in report.failed:
                print(f"  {outcome.path.name}: {outcome.error}")
        if report.needs_review:
            print("\nSee them with: ledgerlocal review")
    return 1 if report.failed and not report.ingested else 0


def _cmd_list(args: argparse.Namespace, config: Config) -> int:
    with Store(config.database) as store:
        records = store.query(**_filters(args))
    if args.json:
        print(json.dumps([_record_dict(record) for record in records], indent=2))
        return 0
    _print_table(records)
    return 0


def _cmd_review(args: argparse.Namespace, config: Config) -> int:
    with Store(config.database) as store:
        records = store.query(**_filters(args), needs_review=True)
    if not records:
        print(f"{GREEN}Nothing flagged.{RESET}")
        return 0
    print(f"{len(records)} document(s) the pipeline is not confident about:\n")
    for record in records:
        amount = "?" if record.total is None else f"{record.total} {record.currency}"
        print(f"  {record.issue_date or 'undated':<10}  {record.vendor[:30]:<30}  {amount:>14}")
        for warning in record.warnings:
            print(f"      {YELLOW}·{RESET} {warning}")
        print(f"      {DIM}{record.filed_path or record.source_path}{RESET}")
        print(f"      {DIM}{record.digest[:12]}{RESET}")
    return 0


def _cmd_export(args: argparse.Namespace, config: Config) -> int:
    with Store(config.database) as store:
        records = store.query(**_filters(args))
    if not records:
        print("Nothing to export.")
        return 0

    out = args.out or (config.library / "exports")
    label = args.period or "all"
    written: list[Path] = []
    if args.format in ("all", "csv"):
        written.append(export.write(out / f"ledgerlocal-{label}.csv", export.records_to_csv(records)))
    if args.format in ("all", "summary-csv"):
        written.append(
            export.write(out / f"ledgerlocal-{label}-by-category.csv", export.summary_csv(records))
        )
    if args.format in ("all", "markdown"):
        written.append(
            export.write(
                out / f"ledgerlocal-{label}.md",
                export.summary_markdown(records, f"Expenses — {label}"),
            )
        )
    for path in written:
        print(f"{GREEN}wrote{RESET}   {path}")
    print(f"\n{len(records)} documents, {export.total_of(records):.2f} total (mixed currencies not converted)")
    return 0


def _cmd_stats(args: argparse.Namespace, config: Config) -> int:
    with Store(config.database) as store:
        records = store.query(**_filters(args))
    if not records:
        print("No documents stored yet. Start with: ledgerlocal ingest <folder>")
        return 0

    buckets = totals_by(records, args.by)
    width = max((len(name) for name in buckets), default=10)
    print(f"{args.by.title():<{width}}  {'Docs':>5}  {'Tax':>12}  {'Total':>14}")
    print("-" * (width + 37))
    for name, bucket in buckets.items():
        print(f"{name:<{width}}  {int(bucket['count']):>5}  {bucket['tax']:>12.2f}  {bucket['total']:>14.2f}")

    flagged = sum(1 for record in records if record.needs_review)
    print(f"\n{len(records)} documents, {flagged} flagged for review")
    return 0


def _cmd_recategorise(args: argparse.Namespace, config: Config) -> int:
    rules = Ruleset.load(config.rules_path)
    with Store(config.database) as store:
        changed = recategorise(store, rules, config)
    print(f"Re-filed {changed} document(s) using {config.rules_path}")
    return 0


def _cmd_show(args: argparse.Namespace, config: Config) -> int:
    with Store(config.database) as store:
        match = next(
            (record for record in store.all_records() if record.digest.startswith(args.digest)),
            None,
        )
        if match is None:
            print(f"No document whose hash starts with {args.digest!r}", file=sys.stderr)
            return 1
        payload = store.payload(match.digest)
    print(json.dumps({"digest": match.digest, "filed_path": match.filed_path, **(payload or {})}, indent=2))
    return 0


# ----------------------------------------------------------------- utils


def _print_table(records: Sequence) -> None:
    if not records:
        print("No documents matched.")
        return
    print(f"{'Date':<11} {'Vendor':<28} {'Category':<18} {'Amount':>14}  Hash")
    print("-" * 88)
    for record in records:
        amount = "?" if record.total is None else f"{record.total} {record.currency}"
        mark = f" {YELLOW}!{RESET}" if record.needs_review else ""
        print(
            f"{record.issue_date or 'undated':<11} {record.vendor[:28]:<28} "
            f"{record.category[:18]:<18} {amount:>14}  {record.digest[:8]}{mark}"
        )
    print(f"\n{len(records)} document(s)")


def _record_dict(record) -> dict:
    return {
        "digest": record.digest,
        "issue_date": record.issue_date,
        "vendor": record.vendor,
        "kind": record.kind,
        "invoice_number": record.invoice_number,
        "category": record.category,
        "client": record.client,
        "currency": record.currency,
        "subtotal": str(record.subtotal) if record.subtotal is not None else None,
        "tax": str(record.tax) if record.tax is not None else None,
        "total": str(record.total) if record.total is not None else None,
        "confidence": record.confidence,
        "warnings": record.warnings,
        "filed_path": record.filed_path,
    }
