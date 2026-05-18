from __future__ import annotations

from typing import Literal

TxCategory = Literal[
    "ACH_PAYABLE",
    "WIRE",
    "CHECK",
    "DEPOSIT_REMOTE",
    "DEPOSIT_CASH",
    "TRANSFER_INTERNAL",
    "PAYROLL",
    "VENDOR_PAYMENT",
    "CARD_PAYMENT",
    "LOAN_PAYMENT",
    "INTEREST",
    "FEE",
    "TAX",
    "OTHER",
]
