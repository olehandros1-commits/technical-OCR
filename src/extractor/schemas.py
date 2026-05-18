"""Pydantic schemas for extracted bank statement data.

These schemas are the contract between LLM extraction and downstream consumers.
They are also used to generate JSON schemas for structured tool calls.
"""
from __future__ import annotations
from typing import Optional, Literal, List
from pydantic import BaseModel, Field, ConfigDict


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str = Field(description="Start of statement period, ISO YYYY-MM-DD")
    end: str = Field(description="End of statement period, ISO YYYY-MM-DD")


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank: str = Field(description="Bank name as printed on statement")
    account_last4: Optional[str] = Field(
        default=None, description="Last 4 digits of account number; null if redacted"
    )
    period: Period


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beginning_balance: float
    ending_balance: float
    deposits_total: float
    deposits_count: Optional[int] = None
    withdrawals_total: float
    withdrawals_count: Optional[int] = None
    currency: Optional[str] = Field(
        default=None,
        description="ISO 4217 currency code (e.g. USD, EUR). null if unclear.",
    )


TxCategory = Literal[
    "ACH_PAYABLE",      # generic AP / payables ACH
    "WIRE",             # wire transfer
    "CHECK",            # paper check
    "DEPOSIT_REMOTE",   # remote/mobile deposit
    "DEPOSIT_CASH",     # branch / ATM cash deposit
    "TRANSFER_INTERNAL",# transfer between own accounts
    "PAYROLL",          # payroll run
    "VENDOR_PAYMENT",   # specific vendor payment
    "CARD_PAYMENT",     # credit card / Amex payment
    "LOAN_PAYMENT",     # loan / mortgage payment
    "INTEREST",         # interest paid by bank
    "FEE",              # service charge / fee
    "TAX",              # tax payment
    "OTHER",
]


class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str = Field(description="Transaction date, ISO YYYY-MM-DD")
    description: str
    deposit: Optional[float] = None
    withdrawal: Optional[float] = None
    # Enrichment fields -- filled by the categorise stage (optional so a
    # bare extraction still validates).
    category: Optional[TxCategory] = None
    vendor: Optional[str] = Field(
        default=None,
        description="Normalised vendor name extracted from the description.",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0, le=1.0,
        description="Model self-reported confidence 0-1 that this row is correct.",
    )


class Anomaly(BaseModel):
    """A potential data-quality concern flagged by the anomaly detector."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "duplicate_pair",
        "date_out_of_period",
        "running_balance_drift",
        "round_number_outlier",
        "size_outlier",
        "low_confidence",
    ]
    severity: Literal["info", "warn", "error"]
    transaction_index: Optional[int] = None  # row index in transactions[]
    related_index: Optional[int] = None      # for paired anomalies
    message: str


class SkippedRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw: str
    reason: str


class ReconciliationResult(BaseModel):
    """Output of deterministic verification stage."""
    model_config = ConfigDict(extra="forbid")
    ok: bool
    deposits_sum: float
    withdrawals_sum: float
    deposits_count_actual: int
    withdrawals_count_actual: int
    deposits_total_delta: float = 0.0
    withdrawals_total_delta: float = 0.0
    deposits_count_delta: int = 0
    withdrawals_count_delta: int = 0
    balance_equation_delta: float = 0.0
    issues: list[str] = Field(default_factory=list)


class Statement(BaseModel):
    """The final output of the extraction pipeline for a single statement."""
    model_config = ConfigDict(extra="forbid")
    account: Account
    summary: Summary
    transactions: list[Transaction]
    skipped_rows: list[SkippedRow] = Field(default_factory=list)
    reconciliation: Optional[ReconciliationResult] = None
    anomalies: list[Anomaly] = Field(default_factory=list)
    recurring: list[dict] = Field(default_factory=list)

    def to_grading_dict(self) -> dict:
        """Return the exact JSON shape required by the task spec."""
        return {
            "account": {
                "bank": self.account.bank,
                "account_last4": self.account.account_last4,
                "period": {
                    "start": self.account.period.start,
                    "end": self.account.period.end,
                },
            },
            "summary": self.summary.model_dump(),
            "transactions": [t.model_dump() for t in self.transactions],
        }
