from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click
from rich.console import Console

from dobs.application.commands.extraction.extract_statement import ExtractStatementCommand
from dobs.main.composition_root import build_container
from dobs.main.config.settings import AppSettings

err = Console(stderr=True)


@click.command()
@click.argument("pdf_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--txt", "txt_path", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--all/--first", "all_statements", default=True)
@click.option("--out", "out_path", type=click.Path(dir_okay=False), default=None)
@click.option("--xlsx", "xlsx_path", type=click.Path(dir_okay=False), default=None)
@click.option("--tier", type=click.Choice(["premium", "balanced", "cheap", "local"], case_sensitive=False), default=None)
@click.option("--backend", type=click.Choice(["anthropic", "ollama"], case_sensitive=False), default=None)
@click.option("--ocr-mode", type=click.Choice(["auto", "vision", "tesseract", "skip"], case_sensitive=False), default="auto", show_default=True)
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
    if backend:
        os.environ["EXTRACTOR_BACKEND"] = backend
    settings = AppSettings()
    container = build_container(settings)
    handler = container.extract_handler()

    command = ExtractStatementCommand(
        pdf_path=pdf_path,
        txt_path=txt_path,
        tier=tier,
        ocr_mode=ocr_mode,
        enrich=enrich,
        parallel=parallel,
    )
    results = await handler(command)

    if not all_statements:
        results = results[:1]

    payload = results if all_statements else (results[0] if results else {})

    def _default(obj):
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        if hasattr(obj, "_asdict"):
            return obj._asdict()
        return str(obj)

    text = json.dumps(payload, indent=2, ensure_ascii=False, default=_default)

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


def main() -> None:
    extract()


if __name__ == "__main__":
    main()
