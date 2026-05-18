from __future__ import annotations
from abc import abstractmethod
from collections.abc import Callable
from typing import Literal, Protocol

OcrMode = Literal["auto", "tesseract", "vision", "text"]


class OcrEnginePort(Protocol):
    @abstractmethod
    async def extract_text(
        self,
        path: str,
        *,
        log_event: Callable | None = None,
    ) -> str:
        raise NotImplementedError
