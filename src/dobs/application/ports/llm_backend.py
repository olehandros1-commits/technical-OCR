from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from dobs.domain.value_objects.image_part import ImagePart
from dobs.domain.value_objects.llm_role import LLMRole

T = TypeVar("T", bound=BaseModel)


class LLMBackendPort(Protocol):
    name: str

    async def call_structured(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        role: LLMRole = LLMRole.EXTRACT,
        max_retries: int = 6,
        cache_system: bool = True,
    ) -> T: ...

    async def call_vision(
        self,
        *,
        system: str,
        user: str,
        images: list[ImagePart],
        response_model: type[T],
        max_retries: int = 6,
    ) -> T: ...

    def supports_vision(self) -> bool: ...
