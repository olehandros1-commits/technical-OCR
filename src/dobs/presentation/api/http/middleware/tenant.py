import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_VALID_TENANT = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
_DEFAULT_TENANT = "_default"

_TENANT_CTX: dict[int, str] = {}


def _normalise_tenant(tid: str | None) -> str:
    if not tid:
        return _DEFAULT_TENANT
    tid = tid.strip()
    if not _VALID_TENANT.match(tid):
        return _DEFAULT_TENANT
    return tid


def current_tenant() -> str:
    import threading

    return _TENANT_CTX.get(threading.get_ident(), _DEFAULT_TENANT)


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        import threading

        tid = _normalise_tenant(request.headers.get("x-tenant-id"))
        ident = threading.get_ident()
        _TENANT_CTX[ident] = tid
        try:
            response = await call_next(request)
        finally:
            _TENANT_CTX.pop(ident, None)
        return response
