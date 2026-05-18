from __future__ import annotations


class DomainError(Exception):
    message: str


class ReconciliationError(DomainError):
    message = "Reconciliation failed"


class InvalidPeriodError(DomainError):
    message = "Statement period is invalid"


class InvalidTransactionError(DomainError):
    message = "Transaction data is invalid"


class StatementAlreadyCachedError(DomainError):
    message = "Statement is already cached"


class ExtractionJobNotFoundError(DomainError):
    message = "Extraction job not found"
