from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str


class PaginationResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
