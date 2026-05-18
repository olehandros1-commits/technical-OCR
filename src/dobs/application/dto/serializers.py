from __future__ import annotations

import dataclasses
from typing import Any


def serialize_results(results: list[Any]) -> list[dict[str, Any]]:
    if not results:
        return []
    if isinstance(results[0], dict):
        return results
    return [dataclasses.asdict(r) for r in results]
