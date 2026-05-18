from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from dobs.application.ports.ocr_engine import OcrEnginePort
from dobs.infrastructure.adapters.ocr.file_reader import (
    IngestError,
    clean_text,
)

if TYPE_CHECKING:
    from dobs.application.ports.llm_backend import LLMBackendPort


class _PageText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_text: str


_SYSTEM = """You are a high-fidelity OCR system for bank statements.

You will receive one or more page images. For each image, transcribe the
text exactly as it appears, preserving:
  * Date columns and amount columns in their original order.
  * Tables: emit row-by-row using simple spaces or | as separators.
  * Section headers on their own line.
  * Currency symbols and commas in numbers.

DO NOT paraphrase, skip redacted blocks (represent them as [REDACTED]),
invent text, or add commentary.

If multiple pages are sent, concatenate them with a single blank line
between pages.

Return the result via the JSON schema with the full transcription in the
`page_text` field."""


def _pdf_pages_to_images(pdf_path: Path, dpi: int = 200) -> list[bytes]:
    from pdf2image import convert_from_path

    images = convert_from_path(str(pdf_path), dpi=dpi)
    out: list[bytes] = []
    for img in images:
        buf = BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


def _batches(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


class VisionOcrEngine(OcrEnginePort):
    def __init__(
        self,
        /,
        *,
        backend: LLMBackendPort,
        dpi: int = 200,
        pages_per_call: int = 3,
    ) -> None:
        self._backend = backend
        self._dpi = dpi
        self._pages_per_call = pages_per_call

    async def extract_text(
        self,
        path: str,
        *,
        log_event: Callable | None = None,
    ) -> str:
        if not self._backend.supports_vision():
            raise IngestError(
                f"Backend does not support vision; use a vision-capable backend for this path."
            )

        p = Path(path)
        pages = await asyncio.to_thread(_pdf_pages_to_images, p, self._dpi)
        transcripts: list[str] = []

        for i, batch in enumerate(_batches(pages, self._pages_per_call)):
            images = [
                {"mime_type": "image/png", "data_b64": base64.b64encode(b).decode("ascii")}
                for b in batch
            ]
            user = (
                f"Transcribe these {len(batch)} bank statement page(s). "
                "Return the JSON object with the full transcription."
            )
            resp = await self._backend.call_vision(
                system=_SYSTEM,
                user=user,
                images=images,
                response_model=_PageText,
            )
            transcripts.append(resp.page_text)
            if log_event:
                log_event("ocr_vision_batch", {
                    "batch": i + 1,
                    "chars": len(resp.page_text),
                })

        return clean_text("\n\n".join(transcripts))
