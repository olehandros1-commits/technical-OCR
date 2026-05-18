"""CLI entry point.

    extract-statement <pdf> [--txt OCR.txt] [--all] [--out result.json]
                      [--backend anthropic|ollama] [--ocr-mode auto|vision|tesseract|skip]

Streams pipeline events to stderr so a live demo shows progress; final JSON
goes to stdout (or the --out file).
"""
from __future__ import annotations
import json
import sys
import logging
import time
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

from extractor.pipeline import extract_all
from extractor.telemetry import TelemetryCollector, set_collector, get_collector
from extractor.export_excel import export_workbook
from extractor.ingest import IngestError
from dotenv import load_dotenv

err = Console(stderr=True)
load_dotenv()


def _make_event_logger():
    t_start = time.time()

    def log_event(name: str, data: dict) -> None:
        elapsed = time.time() - t_start
        err.print(f"[dim][{elapsed:6.2f}s][/dim] [bold cyan]{name}[/bold cyan] {data}")

    return log_event


@click.command()
@click.argument("pdf_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--txt",
    "txt_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Pre-extracted OCR text file (skips OCR stage).",
)
@click.option(
    "--all/--first",
    "all_statements",
    default=True,
    help="Return all statements (default) or only the first one.",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write JSON to file instead of stdout.",
)
@click.option(
    "--xlsx",
    "xlsx_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Also write an Excel workbook (with live formulas) to this path.",
)
@click.option(
    "--tier",
    type=click.Choice(["premium", "balanced", "cheap", "local"], case_sensitive=False),
    default=None,
    help="Named quality/cost profile (overrides --backend when set).",
)
@click.option(
    "--backend",
    type=click.Choice(["anthropic", "ollama"], case_sensitive=False),
    default=None,
    help="LLM backend (defaults to EXTRACTOR_BACKEND env or 'anthropic').",
)
@click.option(
    "--ocr-mode",
    type=click.Choice(["auto", "vision", "tesseract", "skip"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="How to OCR scanned PDFs.",
)
@click.option(
    "--enrich/--no-enrich",
    default=False,
    show_default=True,
    help="Add category, vendor, and confidence to each transaction (+1 LLM call per statement).",
)
@click.option(
    "--parallel",
    type=int,
    default=2,
    show_default=True,
    help="Number of statements to extract in parallel.",
)
@click.option(
    "--cache-path",
    type=click.Path(dir_okay=False),
    default="out/cache.db",
    show_default=True,
    help="SQLite cache path (use '' to disable).",
)
@click.option(
    "--verbose/--quiet",
    default=True,
    help="Stream pipeline events to stderr.",
)
def main(
    pdf_path: str,
    txt_path: str | None,
    all_statements: bool,
    out_path: str | None,
    xlsx_path: str | None,
    tier: str | None,
    backend: str | None,
    ocr_mode: str,
    enrich: bool,
    parallel: int,
    cache_path: str,
    verbose: bool,
) -> None:
    """Extract structured data from a bank statement PDF."""
    logging.basicConfig(
        level=logging.WARNING,
        handlers=[RichHandler(console=err, show_path=False)],
        format="%(message)s",
    )

    log_event = _make_event_logger() if verbose else None

    # Fresh telemetry per run so totals aren't polluted by prior runs.
    set_collector(TelemetryCollector())

    try:
        results = extract_all(
            pdf_path,
            txt_path,
            backend=backend,
            tier=tier,
            ocr_mode=ocr_mode,
            enrich=enrich,
            parallel=parallel,
            cache_path=cache_path or None,
            log_event=log_event,
        )
    except IngestError as e:
        err.print(f"[red]Ingest error:[/red] {e}")
        raise SystemExit(2)

    if not all_statements:
        results = results[:1]

    if verbose:
        err.print()
        err.print(f"[bold]Reconciliation summary[/bold]  (backend={backend or 'default'})")
        ok_count = 0
        for r in results:
            recon = r.get("_reconciliation") or {}
            period = r["account"]["period"]
            ok = recon.get("ok", False)
            ok_count += int(ok)
            mark = "[green]OK[/green]" if ok else "[red]MISMATCH[/red]"
            err.print(
                f"  {mark}  {period['start']} -> {period['end']}  "
                f"acct {r['account']['account_last4']}  "
                f"deposits {recon.get('deposits_count_actual')}/{r['summary'].get('deposits_count')}  "
                f"withdrawals {recon.get('withdrawals_count_actual')}/{r['summary'].get('withdrawals_count')}"
            )
            for issue in recon.get("issues", []):
                err.print(f"      [yellow]- {issue}[/yellow]")
        err.print(f"\n{ok_count}/{len(results)} statements reconciled.\n")

        tel = get_collector().summary()
        if tel.get("total_calls", 0) > 0:
            err.print("[bold]Telemetry[/bold]")
            err.print(
                f"  calls={tel['total_calls']}  "
                f"in_tok={tel['total_input_tokens']:,}  "
                f"out_tok={tel['total_output_tokens']:,}  "
                f"cache_read={tel['total_cache_read']:,}  "
                f"elapsed_s={tel['total_elapsed_s']:.1f}  "
                f"cost=[green]${tel['total_cost_usd']:.4f}[/green]"
            )
            err.print()

    payload = results if all_statements else (results[0] if results else {})
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
        err.print(f"[green]Wrote[/green] {out_path}")
    else:
        sys.stdout.write(text + "\n")

    if xlsx_path and results:
        path = export_workbook(results, xlsx_path)
        err.print(f"[green]Wrote Excel workbook[/green] {path}")


if __name__ == "__main__":
    main()
