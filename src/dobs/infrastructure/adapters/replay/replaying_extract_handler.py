from __future__ import annotations

import asyncio
from typing import Any

from dobs.application.commands.extraction.extract_statement import (
    ExtractStatementCommand,
    ExtractStatementHandler,
)
from dobs.application.ports.event_bus import EventBusPort
from dobs.infrastructure.adapters.replay.demo_replay import (
    DemoReplayPlayer,
    is_replay_enabled,
)


class ReplayingExtractHandler:
    def __init__(
        self,
        /,
        *,
        inner: ExtractStatementHandler,
        replay_player: DemoReplayPlayer,
        event_bus: EventBusPort,
    ) -> None:
        self._inner = inner
        self._replay = replay_player
        self._event_bus = event_bus

    async def __call__(self, command: ExtractStatementCommand) -> list[Any]:
        if is_replay_enabled():
            bus = self._event_bus

            def log_event(name: str, data: dict[str, Any]) -> None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(bus.publish(name, data))
                except RuntimeError:
                    pass

            return await self._replay.replay(
                log_event=log_event,
                tier=getattr(command, "tier", None),
            )
        return await self._inner(command)
