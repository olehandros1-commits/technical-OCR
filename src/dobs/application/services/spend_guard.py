from __future__ import annotations

import asyncio

from dobs.application.errors import SpendCapExceededError


class SpendGuard:
    def __init__(
        self,
        /,
        *,
        cap_usd: float | None = None,
        warn_at_ratio: float = 0.8,
    ) -> None:
        self._cap_usd = cap_usd if cap_usd is not None else float("inf")
        self._warn_at_ratio = warn_at_ratio
        self._spent = 0.0
        self._warned = False
        self._lock = asyncio.Lock()

    @property
    def spent(self) -> float:
        return self._spent

    def remaining(self) -> float:
        return max(0.0, self._cap_usd - self._spent)

    async def record(self, delta_usd: float) -> tuple[bool, bool]:
        warn = False
        breached = False
        async with self._lock:
            self._spent += delta_usd
            ratio = self._spent / self._cap_usd if self._cap_usd > 0 else 0.0
            if not self._warned and ratio >= self._warn_at_ratio and self._cap_usd != float("inf"):
                warn = True
                self._warned = True
            if self._cap_usd != float("inf") and self._spent > self._cap_usd:
                breached = True
        if breached:
            raise SpendCapExceededError(
                f"Spend cap exceeded: spent ${self._spent:.4f} of "
                f"${self._cap_usd:.2f} cap. Aborting."
            )
        return warn, breached
