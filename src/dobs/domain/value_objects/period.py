from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, kw_only=True, slots=True)
class Period:
    start: str
    end: str

    def as_dates(self) -> tuple[date, date]:
        return date.fromisoformat(self.start), date.fromisoformat(self.end)
