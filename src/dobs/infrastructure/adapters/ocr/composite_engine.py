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


class CompositeOcrEngine(OcrEnginePort):
    def __init__(
        self,
        /,
        *,
        file_reader: FileReader,
        tesseract: TesseractOcrEngine,
        vision: VisionOcrEngine | None,
    ) -> None:
        self._file_reader = file_reader
        self._tesseract = tesseract
        self._vision = vision

    async def extract_text(
        self,
        path: str,
        *,
        log_event: Callable | None = None,
        ocr_mode: OcrMode = "auto",
    ) -> str:
        p = Path(path)
        if not p.exists():
            raise IngestError(f"File not found: {p}")

        kind = detect_kind(p)

        if kind != "pdf":
            return await self._tesseract.extract_text(path, log_event=log_event)

        if ocr_mode == "vision":
            if self._vision is None:
                raise ValueError("ocr_mode='vision' requires a VisionOcrEngine")
            return await self._extract_pdf_vision(path, log_event)

        if ocr_mode == "tesseract":
            return await self._tesseract.extract_text(path, log_event=log_event)

        if ocr_mode == "skip":
            return await asyncio.to_thread(self._file_reader.from_pdf_text, p)

        text = await asyncio.to_thread(self._file_reader.from_pdf_text, p)
        if len(text.strip()) >= 200:
            return text

        if self._vision is not None and self._vision._backend.supports_vision():
            return await self._extract_pdf_vision(path, log_event)

        return await self._tesseract.extract_text(path, log_event=log_event)

    async def _extract_pdf_vision(
        self,
        path: str,
        log_event: Callable | None = None,
    ) -> str:
        assert self._vision is not None
        return await self._vision.extract_text(path, log_event=log_event)
