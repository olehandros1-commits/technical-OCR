from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from dobs.domain.entities.base import Entity

JobStatus = Literal["pending", "running", "done", "failed"]


@dataclass(eq=False, kw_only=True)
class ExtractionJob(Entity[UUID]):
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None = None
    result_ref: str | None = None
