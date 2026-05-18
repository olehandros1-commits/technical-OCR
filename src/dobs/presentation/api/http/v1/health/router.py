from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/health", tags=["health"])

_WARMED: dict[str, bool] = {"done": False}


@router.get("")
async def health() -> dict:
    if not _WARMED["done"]:
        _WARMED["done"] = True
        _trigger_warmup()
    return {"ok": True, "service": "dobs-extractor"}


def _trigger_warmup() -> None:
    import os
    import threading

    if os.getenv("EXTRACTOR_WARMUP", "1") not in {"1", "true", "yes"}:
        return
    try:
        from extractor.backends import get_backend
        from extractor.warmup import warm_up_backend

        backend = get_backend()
        threading.Thread(target=lambda: warm_up_backend(backend), daemon=True).start()
    except Exception:
        pass
