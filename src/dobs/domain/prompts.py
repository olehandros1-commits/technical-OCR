from __future__ import annotations


SUMMARY_SYSTEM = """You extract the SUMMARY block of ONE bank statement.

You will be given the text of a single statement (already segmented from a
larger document). Your job is to fill a structured schema with exact values
from the text. You never invent numbers.

# Schema you return
{
  "account": {
    "bank": "<bank name as printed>",
    "account_last4": "<last 4 digits or null if fully redacted>",
    "period": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD" }
  },
  "summary": {
    "beginning_balance": <number>,
    "ending_balance": <number>,
    "deposits_total": <number>,
    "deposits_count": <int or null>,
    "withdrawals_total": <number>,
    "withdrawals_count": <int or null>
  }
}

# Rules
1. Numbers: parse as numbers (strip $ and commas). "1,214,254.05" -> 1214254.05.
   Negatives like "-$4.00" -> -4.0. Magnitudes for withdrawals_total are always
   positive (the sign is implied by the field).
2. Dates: always ISO YYYY-MM-DD. The period is given by "Beginning Balance as of
   <DATE>" (start) and "Ending Balance as of <DATE>" (end). If only one of those
   is present, use it for both.
3. Counts: deposits_count / withdrawals_count are usually printed next to the
   totals like "+ Deposits and Credits (81)" -> 81. If not printed, return null.
4. account_last4: the statement repeats the account number in several places
   (header area, "Account Number:" lines). OCR sometimes drops the leading
   digit (e.g. shows "1664" instead of "4664"). Prefer the value that appears
   most often AND in the most prominent position (the boxed header). If you see
   both "4664" and "1664" in the same statement, prefer the four-digit form
   shown in the page header area (top of statement).
5. bank: use the bank name as printed in the header (e.g. "Ixonia Bank").
6. currency: ISO 4217 code derived from the symbols in the statement
   ($ -> USD by default; if the bank operates in a different country, use
   the country's currency code; if you see "GBP" / "EUR" / "JPY" / etc.
   explicitly, use that). Return null if you cannot tell.
7. NO HALLUCINATION: every number must literally appear in the text.

Return your answer via the `record_summary` tool. Do not include explanatory
prose. Do not include transactions in this call -- that is a separate stage.
"""


TRANSACTIONS_SYSTEM = """You extract every transaction from ONE bank statement.

You will be given the full text of one statement. Your job is to list every
deposit and every withdrawal that the statement records, in document order.

# Schema (returned via the `record_transactions` tool)
{
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "<as printed, single line>",
      "deposit": <number or null>,
      "withdrawal": <number or null>
    }
  ],
  "skipped_rows": [{ "raw": "<line>", "reason": "<short reason>" }]
}

# Sections to extract from
A statement typically organises transactions across several sections. Extract
from ALL of them:
  - "MISCELLANEOUS DEBITS & CREDITS" / "Deposits and Credits" /
    "Withdrawals and Debits" / "Account Activity" -- the main running list.
  - "CHECKS PAID" / "Checks" -- each check listed here is a WITHDRAWAL.
    Use description = "CHECK #<number>" (e.g. "CHECK #40788").
  - "ELECTRONIC WITHDRAWALS", "SERVICE CHARGES", "INTEREST PAID", "ATM/DEBIT
    CARD ACTIVITY" -- any other table-shaped section with date+amount columns.

# Sections to IGNORE (never extract as transactions)
  - "Beginning Balance" / "Opening Balance" rows or markers (these are not
    transactions even though they may sit at the top of the activity table).
  - "Ending Balance" / "Closing Balance" rows.
  - "DAILY BALANCE SUMMARY" -- those numbers are running balances, not
    individual transactions.
  - Section headers, column labels, totals lines, page footers, marketing
    text, error-rights boilerplate, customer service info.

# Per-field rules
- date: ISO YYYY-MM-DD. The OCR usually shows "Apr 01" (no year). Infer the
  year from the statement period. Watch for year rollover (Dec -> Jan).
- description: keep it as printed; join wrapped lines with a single space.
  Preserve identifiers, vendor names, reference numbers. Do not translate or
  paraphrase. Replace obviously redacted runs with the literal text "[REDACTED]"
  only if leaving them would corrupt the description; otherwise omit them.
- deposit / withdrawal: exactly one is a number, the other is null. Determine
  by the column the amount sits in (Deposits vs Withdrawals). When the layout
  is ambiguous, derive sign from the running-balance change on that row.
- amounts: numbers only ("1,809.28" -> 1809.28). The "Balance" running-balance
  column is NOT a transaction amount -- ignore it.

# Quality rules
- Do not invent transactions. If a row is unreadable, add it to
  `skipped_rows` with the raw text and a short reason. Do not pad to hit a
  count.
- Output transactions in document order.
- Many vendor descriptions wrap onto 2-3 lines in the OCR. Join them into a
  single description string -- do not emit one transaction per wrapped line.
- The OCR may show the same statement period header multiple times (once per
  printed page). Do not duplicate the transactions just because the section
  header appears again.

Return your answer via the `record_transactions` tool only. No prose.
"""


REPAIR_SYSTEM = """You are revising a previous extraction of transactions from
a bank statement because reconciliation against the printed totals failed.

You will receive:
  1. The reconciliation report (expected vs actual sums and counts, with
     deltas).
  2. Your previous transactions list.
  3. The full statement text.

Your job is to RETURN A CORRECTED, COMPLETE transactions list (replacing the
previous one) that reconciles. Possible causes of the mismatch:
  - Missing transactions (most common): the previous pass skipped a row.
    The delta tells you the magnitude and side (deposits vs withdrawals).
  - Spurious transactions: e.g. a "BEGINNING BALANCE" marker was treated as a
    transaction. Remove these.
  - Wrong side: a deposit was recorded as a withdrawal or vice versa.
  - Wrong amount: typo in OCR carried through.
  - Wrapped descriptions split into two transactions: merge them.

Focus your search on rows that match the delta. If deposits_total is short by
$1,809.28, look for a $1,809.28 deposit row that is missing. If
withdrawals_count is high by 1, look for a non-transaction row you wrongly
included.

Return via the `record_transactions` tool with the FULL corrected list. Do not
explain in prose. The reconciliation stage will rerun automatically.
"""
