from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from dobs.application.ports.event_bus import EventBusPort

log = logging.getLogger(__name__)

_current_bus: ContextVar[EventBusPort | None] = ContextVar("dobs_event_bus", default=None)


class ContextEventBus(EventBusPort):
    async def publish(self, event_name: str, data: dict[str, object]) -> None:
        bus = _current_bus.get()
        if bus is None:
            log.debug("publish(%s) outside bound context — dropped", event_name)
            return
        await bus.publish(event_name, data)


@contextmanager
def bind_event_bus(bus: EventBusPort) -> Iterator[None]:
    token = _current_bus.set(bus)
    try:
        yield
    finally:
        _current_bus.reset(token)
