import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _configured_origins() -> list[str]:
    raw = os.getenv("EXTRACTOR_CORS_ALLOW", "*")
    return [o.strip() for o in raw.split(",") if o.strip()]


def configured_cors(app: FastAPI) -> None:
    origins = _configured_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False if origins == ["*"] else True,
    )
