from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

OcrMode = Literal["auto", "tesseract", "vision", "text", "opendataloader", "skip"]


class OcrEnginePort(Protocol):
    async def extract_text(
        self,
        path: str,
        *,
        log_event: Callable[..., object] | None = None,
    ) -> str: ...
