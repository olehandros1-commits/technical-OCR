from __future__ import annotations

from enum import StrEnum


class LLMRole(StrEnum):
    CHEAP = "cheap"
    EXTRACT = "extract"
    REPAIR = "repair"
    VISION = "vision"
