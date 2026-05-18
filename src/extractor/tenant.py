"""Per-tenant isolation: a small key namespace that flows through cache,
audit, reviews, and lessons.

A tenant is identified by an X-Tenant-ID header (or `tenant` form field
on file uploads). When set, every storage key the pipeline writes is
prefixed with the tenant id so two customers cannot accidentally see
each other's cached results, audit rows, or HITL decisions.

Anonymous = `_default`. Tenants are opaque strings; production would
back this with OIDC subject claims, but the storage contract is
identical.
"""
from __future__ import annotations
import re
import threading
from contextlib import contextmanager
from typing import Iterator

_VALID = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
_DEFAULT = "_default"

_TLS = threading.local()


def normalise_tenant(tid: str | None) -> str:
    """Accept anything sensible; reject suspicious values silently to
    avoid path traversal via cache keys."""
    if not tid:
        return _DEFAULT
    tid = tid.strip()
    if not _VALID.match(tid):
        return _DEFAULT
    return tid


def current_tenant() -> str:
    return getattr(_TLS, "tenant", _DEFAULT)


@contextmanager
def tenant_scope(tenant: str | None) -> Iterator[str]:
    """Bind a tenant id for the duration of a request / job thread."""
    prev = getattr(_TLS, "tenant", None)
    _TLS.tenant = normalise_tenant(tenant)
    try:
        yield _TLS.tenant
    finally:
        if prev is None:
            delattr(_TLS, "tenant")
        else:
            _TLS.tenant = prev


def scoped_key(key: str) -> str:
    """Prefix a storage key with the active tenant so per-tenant
    namespaces never collide."""
    return f"{current_tenant()}::{key}"
