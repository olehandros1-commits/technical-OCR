from __future__ import annotations

from dataclasses import dataclass

from dobs.application.ports.telemetry_collector import TelemetryCollectorPort


@dataclass(frozen=True, kw_only=True, slots=True)
class GetTelemetryQuery:
    pass


class GetTelemetryHandler:
    def __init__(
        self,
        /,
        *,
        telemetry: TelemetryCollectorPort,
    ) -> None:
        self._telemetry = telemetry

    async def __call__(self, query: GetTelemetryQuery) -> dict:
        return self._telemetry.summary()
