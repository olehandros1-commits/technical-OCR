from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click
from rich.console import Console

err = Console(stderr=True)


def _get_handler():
    raise NotImplementedError("Composition root must wire ExtractStatementHandler before calling CLI")


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
    help="Also write an Excel workbook to this path.",
)
@click.option(
    "--tier",
    type=click.Choice(["premium", "balanced", "cheap", "local"], case_sensitive=False),
    default=None,
    help="Named quality/cost profile.",
)
@click.option(
    "--backend",
    type=click.Choice(["anthropic", "ollama"], case_sensitive=False),
    default=None,
    help="LLM backend.",
)
@click.option(
    "--ocr-mode",
    type=click.Choice(["auto", "vision", "tesseract", "skip"], case_sensitive=False),
    default="auto",
    show_default=True,
)
@click.option("--enrich/--no-enrich", default=False, show_default=True)
@click.option("--parallel", type=int, default=2, show_default=True)
@click.option("--verbose/--quiet", default=True)
def extract(
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
    verbose: bool,
) -> None:
    """Extract structured data from a bank statement PDF."""
    asyncio.run(
        _run(
            pdf_path=pdf_path,
            txt_path=txt_path,
            all_statements=all_statements,
            out_path=out_path,
            xlsx_path=xlsx_path,
            tier=tier,
            backend=backend,
            ocr_mode=ocr_mode,
            enrich=enrich,
            parallel=parallel,
            verbose=verbose,
        )
    )


async def _run(
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
    verbose: bool,
) -> None:
    handler = _get_handler()
    results = await handler(
        pdf_path=Path(pdf_path),
        txt_path=Path(txt_path) if txt_path else None,
        backend=backend,
        tier=tier,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
    )

    if not all_statements:
        results = results[:1]

    payload = results if all_statements else (results[0] if results else {})
    text = json.dumps(payload, indent=2, ensure_ascii=False)

    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
        if verbose:
            err.print(f"[green]Wrote[/green] {out_path}")
    else:
        sys.stdout.write(text + "\n")

    if xlsx_path and results:
        from dobs.presentation.export.excel import export_workbook

        path = export_workbook(results, xlsx_path)
        if verbose:
            err.print(f"[green]Wrote Excel workbook[/green] {path}")


if __name__ == "__main__":
    extract()
