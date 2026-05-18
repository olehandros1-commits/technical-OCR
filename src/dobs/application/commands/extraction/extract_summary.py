from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from dobs.application.ports.llm_backend import LLMBackendPort
from dobs.domain.prompts import SUMMARY_SYSTEM
from dobs.domain.services.prompt_sanitizer import safe_wrap
from dobs.domain.value_objects.account import Account
from dobs.domain.value_objects.llm_role import LLMRole
from dobs.domain.value_objects.summary import Summary


class _SummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: Account
    summary: Summary


@dataclass(frozen=True, kw_only=True, slots=True)
class ExtractSummaryCommand:
    segment_text: str


class ExtractSummaryHandler:
    def __init__(
        self,
        /,
        *,
        llm: LLMBackendPort,
    ) -> None:
        self._llm = llm

    async def __call__(self, command: ExtractSummaryCommand) -> tuple[Account, Summary]:
        head = command.segment_text[:6000]
        wrapped, _ = safe_wrap(head)
        user = (
            "Below is the text of one bank statement (truncated to the summary "
            "area), wrapped in DOCUMENT_TEXT fences. Extract the structured "
            "`account` and `summary` blocks and return them as a JSON object "
            "matching the schema.\n\n"
            f"{wrapped}"
        )
        resp = await self._llm.call_structured(
            system=SUMMARY_SYSTEM,
            user=user,
            response_model=_SummaryResponse,
            role=LLMRole.CHEAP,
        )
        return resp.account, resp.summary
