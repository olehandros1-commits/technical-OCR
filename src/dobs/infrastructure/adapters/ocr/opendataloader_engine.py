from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dobs.application.ports.ocr_engine import OcrEnginePort

log = logging.getLogger(__name__)


class OpenDataLoaderOcrEngine(OcrEnginePort):
    def __init__(
        self,
        /,
        *,
        jar_path: Path | None = None,
        java_bin: str = "java",
        java_opts: tuple[str, ...] = ("-Xmx2g",),
        timeout_s: float = 600.0,
        hybrid_url: str | None = None,
    ) -> None:
        env_jar = os.getenv("OPENDATALOADER_JAR")
        self._jar = jar_path or (Path(env_jar) if env_jar else None)
        self._java = shutil.which(java_bin) or java_bin
        self._java_opts = java_opts
        self._timeout = timeout_s
        self._hybrid_url = hybrid_url or os.getenv("OPENDATALOADER_HYBRID_URL")
        if self._jar is None or not self._jar.exists():
            raise FileNotFoundError(
                "OpenDataLoaderOcrEngine requires either jar_path= "
                "or OPENDATALOADER_JAR env to point at a downloaded jar."
            )

    async def extract_text(
        self,
        path: str,
        *,
        log_event: Callable[..., object] | None = None,
    ) -> str:
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"PDF not found: {src}")

        with tempfile.TemporaryDirectory(prefix="opendataloader_") as out_dir:
            out = Path(out_dir)
            args: list[str] = [
                self._java,
                *self._java_opts,
                "-jar",
                str(self._jar),
                "-f",
                "json",
                "-o",
                str(out),
                "--quiet",
            ]
            if self._hybrid_url:
                args.extend([
                    "--hybrid", "docling-fast",
                    "--hybrid-url", self._hybrid_url,
                    "--hybrid-fallback",
                ])
            args.append(str(src))
            if log_event:
                log_event("opendataloader_start", {
                    "hybrid": bool(self._hybrid_url),
                    "source": src.name,
                })
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(
                    f"opendataloader-pdf timed out after {self._timeout}s on {src.name}"
                ) from None

            if proc.returncode != 0:
                detail = (stderr or stdout or b"").decode("utf-8", errors="ignore")[:1500]
                raise RuntimeError(
                    f"opendataloader-pdf failed (rc={proc.returncode}): {detail}"
                )

            json_files = sorted(out.rglob("*.json"))
            if not json_files:
                raise RuntimeError(f"opendataloader produced no JSON in {out} for {src.name}")

            payload = json.loads(json_files[0].read_text(encoding="utf-8"))
            text = self._render_text(payload)
            if len(text.strip()) < 200:
                raise RuntimeError(
                    f"opendataloader produced only {len(text.strip())} chars of text "
                    f"for {src.name} (likely scanned PDF without text layer; falling back)"
                )
            if log_event:
                log_event(
                    "opendataloader_extracted",
                    {
                        "chars": len(text),
                        "json_files": len(json_files),
                        "source": src.name,
                        "hybrid": bool(self._hybrid_url),
                    },
                )
            return text

    def _render_text(self, payload: Any) -> str:
        chunks: list[str] = []
        self._walk(payload, chunks)
        return "\n".join(c for c in chunks if c.strip())

    def _walk(self, node: Any, out: list[str]) -> None:
        if isinstance(node, dict):
            content = node.get("content")
            if isinstance(content, str):
                out.append(content)
            elif isinstance(content, list):
                for child in content:
                    self._walk(child, out)
            text = node.get("text")
            if isinstance(text, str) and text != content:
                out.append(text)
            for key, value in node.items():
                if key in {"content", "text"}:
                    continue
                self._walk(value, out)
        elif isinstance(node, list):
            for item in node:
                self._walk(item, out)
