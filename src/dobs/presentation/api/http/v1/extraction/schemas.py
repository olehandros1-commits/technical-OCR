from pydantic import BaseModel


class ExtractRequest(BaseModel):
    backend: str = "anthropic"
    tier: str = ""
    ocr_mode: str = "auto"
    enrich: bool = False
    parallel: int = 2


class ExtractResponse(BaseModel):
    results: list[dict]
    telemetry: dict


class JobCreatedResponse(BaseModel):
    job_id: str


class JobResultResponse(BaseModel):
    job_id: str
    done: bool
    results: list[dict] | None = None
    error: str | None = None
