"""HTTP-layer security: optional API key middleware + tight CORS preset.

Enabled by environment variables -- off by default for local demos:

  EXTRACTOR_API_KEYS   comma-separated list of allowed keys (e.g. "k1,k2").
                       If unset, the API is open (good for `pnpm dev`).
  EXTRACTOR_CORS_ALLOW comma-separated list of allowed origins. Default:
                       '*' (open). Set e.g. 'https://your-ui.example.com'
                       in production.

When `EXTRACTOR_API_KEYS` is set, requests must include either:
  * header  `X-API-Key: <key>`
  * or query `?api_key=<key>`
or they get a 401.
"""
from __future__ import annotations
import os
from typing import Iterable

from fastapi import HTTPException, Request


def configured_keys() -> set[str]:
    raw = os.getenv("EXTRACTOR_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def configured_cors() -> list[str]:
    raw = os.getenv("EXTRACTOR_CORS_ALLOW", "*")
    return [o.strip() for o in raw.split(",") if o.strip()]


async def api_key_dependency(request: Request) -> None:
    """FastAPI dependency: enforces X-API-Key when keys are configured."""
    keys = configured_keys()
    if not keys:
        return  # open mode
    candidate = (
        request.headers.get("x-api-key")
        or request.query_params.get("api_key")
    )
    if candidate not in keys:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
