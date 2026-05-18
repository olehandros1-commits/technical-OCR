from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar

_VALID = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
_DEFAULT = "_default"

_CURRENT_TENANT: ContextVar[str] = ContextVar("current_tenant", default=_DEFAULT)


def _normalise(tid: str | None) -> str:
    if not tid:
        return _DEFAULT
    tid = tid.strip()
    if not _VALID.match(tid):
        return _DEFAULT
    return tid


class ContextTenantBinder:
    def __init__(self, /) -> None:
        pass

    def current(self) -> str:
        return _CURRENT_TENANT.get()

    @asynccontextmanager
    async def tenant_scope(self, tenant: str | None) -> AsyncGenerator[str, None]:
        token = _CURRENT_TENANT.set(_normalise(tenant))
        try:
            yield _CURRENT_TENANT.get()
        finally:
            _CURRENT_TENANT.reset(token)

    def scoped_key(self, key: str) -> str:
        return f"{self.current()}::{key}"
