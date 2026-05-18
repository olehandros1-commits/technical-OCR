from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from dobs.application.ports.ocr_engine import OcrEnginePort, OcrMode
from dobs.infrastructure.adapters.ocr.file_reader import (
    FileReader,
    IngestError,
    detect_kind,
)
from dobs.infrastructure.adapters.ocr.tesseract_engine import TesseractOcrEngine
from dobs.infrastructure.adapters.ocr.vision_engine import VisionOcrEngine

_MIN_USABLE_CHARS = 500
_MIN_PRINTABLE_RATIO = 0.75


def _is_usable_ocr(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < _MIN_USABLE_CHARS:
        return False
    printable = sum(1 for c in stripped if c.isprintable() or c in "\n\t")
    return printable / len(stripped) >= _MIN_PRINTABLE_RATIO


class CompositeOcrEngine(OcrEnginePort):
    def __init__(
        self,
        /,
        *,
        file_reader: FileReader,
        tesseract: TesseractOcrEngine,
        vision: VisionOcrEngine | None,
        opendataloader: OcrEnginePort | None = None,
    ) -> None:
        self._file_reader = file_reader
        self._tesseract = tesseract
        self._vision = vision
        self._opendataloader = opendataloader

    async def extract_text(
        self,
        path: str,
        *,
        log_event: Callable[..., object] | None = None,
        ocr_mode: OcrMode = "auto",
    ) -> str:
        p = Path(path)
        if not p.exists():
            raise IngestError(f"File not found: {p}")

        kind = detect_kind(p)

        if kind != "pdf":
            return await self._tesseract.extract_text(path, log_event=log_event)

        if ocr_mode == "opendataloader":
            if self._opendataloader is None:
                raise ValueError("ocr_mode='opendataloader' requires the engine to be wired")
            return await self._opendataloader.extract_text(path, log_event=log_event)

        if ocr_mode == "vision":
            if self._vision is None:
                raise ValueError("ocr_mode='vision' requires a VisionOcrEngine")
            return await self._vision.extract_text(path, log_event=log_event)

        if ocr_mode == "tesseract":
            return await self._tesseract.extract_text(path, log_event=log_event)

        if ocr_mode == "skip":
            return await asyncio.to_thread(self._file_reader.from_pdf_text, p)

        if self._opendataloader is not None:
            try:
                return await self._opendataloader.extract_text(path, log_event=log_event)
            except Exception:
                pass

        text = await asyncio.to_thread(self._file_reader.from_pdf_text, p)
        if len(text.strip()) >= 200:
            return text

        if self._opendataloader is not None:
            try:
                return await self._opendataloader.extract_text(path, log_event=log_event)
            except Exception:
                pass

        tesseract_text: str | None = None
        try:
            tesseract_text = await self._tesseract.extract_text(path, log_event=log_event)
        except Exception:
            if self._vision is not None and self._vision._backend.supports_vision():
                if log_event:
                    log_event("ocr_vision_escalate", {"reason": "tesseract_failed"})
                return await self._vision.extract_text(path, log_event=log_event)
            raise

        if _is_usable_ocr(tesseract_text):
            return tesseract_text

        if self._vision is not None and self._vision._backend.supports_vision():
            if log_event:
                log_event(
                    "ocr_vision_escalate",
                    {
                        "reason": "tesseract_low_quality",
                        "chars": len(tesseract_text.strip()),
                    },
                )
            return await self._vision.extract_text(path, log_event=log_event)
        return tesseract_text
