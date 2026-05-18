from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True, slots=True)
class ImagePart:
    mime_type: str
    data_b64: str
