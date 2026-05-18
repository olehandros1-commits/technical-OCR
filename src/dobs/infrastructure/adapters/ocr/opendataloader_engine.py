from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from dobs.application.ports.ocr_engine import OcrEnginePort


class OpenDataLoaderOcrEngine(OcrEnginePort):
    def __init__(
        self,
        /,
        *,
        jar_path: Path | None = None,
        java_bin: str = "java",
        java_opts: tuple[str, ...] = ("-Xmx2g",),
    ) -> None:
        env_jar = os.getenv("OPENDATALOADER_JAR")
        self._jar = jar_path or (Path(env_jar) if env_jar else None)
        self._java = shutil.which(java_bin) or java_bin
        self._java_opts = java_opts
        if self._jar is None or not self._jar.exists():
            raise FileNotFoundError(
                "OpenDataLoaderOcrEngine requires either jar_path= "
                "or OPENDATALOADER_JAR env to point at a downloaded jar."
            )

    async def extract_text(
        self,
        path: str,
        *,
        log_event: Callable | None = None,
    ) -> str:
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"PDF not found: {src}")

        with tempfile.TemporaryDirectory(prefix="opendataloader_") as out_dir:
            out = Path(out_dir)
            proc = await asyncio.create_subprocess_exec(
                self._java, *self._java_opts,
                "-jar", str(self._jar),
                "--input", str(src),
                "--output", str(out),
                "--format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                detail = (stderr or stdout or b"").decode("utf-8", errors="ignore")[:1000]
                raise RuntimeError(
                    f"opendataloader-pdf failed (rc={proc.returncode}): {detail}"
                )

            json_files = sorted(out.glob("*.json"))
            if not json_files:
                raise RuntimeError(
                    f"opendataloader produced no JSON in {out} for {src.name}"
                )

            payload = json.loads(json_files[0].read_text(encoding="utf-8"))
            text = self._render_text(payload)
            if log_event:
                log_event("opendataloader_extracted", {
                    "chars": len(text), "blocks": _count_blocks(payload),
                })
            return text

    def _render_text(self, payload: dict | list) -> str:
        chunks: list[str] = []
        self._walk(payload, chunks)
        return "\n".join(c for c in chunks if c.strip())

    def _walk(self, node: object, out: list[str]) -> None:
        if isinstance(node, dict):
            text = node.get("text")
            if isinstance(text, str):
                out.append(text)
            for value in node.values():
                self._walk(value, out)
        elif isinstance(node, list):
            for item in node:
                self._walk(item, out)


def _count_blocks(payload: object) -> int:
    if isinstance(payload, list):
        return sum(_count_blocks(x) for x in payload)
    if isinstance(payload, dict):
        return 1 + sum(_count_blocks(v) for v in payload.values())
    return 0
