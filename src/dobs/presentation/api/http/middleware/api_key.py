import os

from fastapi import HTTPException, Request


def _configured_keys() -> set[str]:
    raw = os.getenv("EXTRACTOR_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


async def api_key_dependency(request: Request) -> None:
    keys = _configured_keys()
    if not keys:
        return
    candidate = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if candidate not in keys:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
