from __future__ import annotations


class ApplicationError(Exception):
    message: str = "Application error"


class NotABankStatementError(ApplicationError):
    message = "Document is not a bank statement"


class SpendCapExceededError(ApplicationError):
    message = "Spend cap exceeded"


class IngestError(ApplicationError):
    message = "Failed to ingest document"


class ExtractionFailedError(ApplicationError):
    message = "Extraction failed"
