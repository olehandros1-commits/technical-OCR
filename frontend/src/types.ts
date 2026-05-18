// Mirrors the Pydantic schemas in src/extractor/schemas.py.
// Keep these in sync when you change the Python side.

export type Backend = "anthropic" | "ollama";
export type OcrMode = "auto" | "vision" | "tesseract" | "skip";
export type Tier = "premium" | "balanced" | "cheap" | "local";

export interface TierInfo {
  name: Tier;
  display: string;
  description: string;
  backend: Backend;
  model_cheap: string;
  model_extract: string;
  model_repair: string;
  expected_latency_s: [number, number];
  expected_cost_usd:  [number, number];
  enrich_default: boolean;
  ocr_mode: OcrMode;
}

export type TxCategory =
  | "ACH_PAYABLE" | "WIRE" | "CHECK" | "DEPOSIT_REMOTE" | "DEPOSIT_CASH"
  | "TRANSFER_INTERNAL" | "PAYROLL" | "VENDOR_PAYMENT" | "CARD_PAYMENT"
  | "LOAN_PAYMENT" | "INTEREST" | "FEE" | "TAX" | "OTHER";

export interface Period { start: string; end: string }

export interface Account {
  bank: string;
  account_last4: string | null;
  period: Period;
}

export interface Summary {
  beginning_balance: number;
  ending_balance: number;
  deposits_total: number;
  deposits_count: number | null;
  withdrawals_total: number;
  withdrawals_count: number | null;
  currency: string | null;
}

export interface Transaction {
  date: string;
  description: string;
  deposit: number | null;
  withdrawal: number | null;
  category: TxCategory | null;
  vendor: string | null;
  confidence: number | null;
  // Optional fields added by vendor enrichment post-processor.
  _vendor_logo?: string | null;
  _vendor_domain?: string | null;
  _vendor_canonical?: string | null;
}

export type AnomalyKind =
  | "duplicate_pair" | "date_out_of_period" | "running_balance_drift"
  | "round_number_outlier" | "size_outlier" | "low_confidence";
export type AnomalySeverity = "info" | "warn" | "error";

export interface Anomaly {
  kind: AnomalyKind;
  severity: AnomalySeverity;
  transaction_index: number | null;
  related_index: number | null;
  message: string;
}

export interface Reconciliation {
  ok: boolean;
  deposits_sum: number;
  withdrawals_sum: number;
  deposits_count_actual: number;
  withdrawals_count_actual: number;
  deposits_total_delta: number;
  withdrawals_total_delta: number;
  deposits_count_delta: number;
  withdrawals_count_delta: number;
  balance_equation_delta: number;
  issues: string[];
}

export interface RecurringGroup {
  vendor_key: string;
  side: "deposit" | "withdrawal";
  avg_amount: number;
  cadence_days: number;
  cadence_label: "weekly" | "fortnightly" | "monthly" | "quarterly" | "irregular";
  count: number;
  occurrences: number[];
  next_predicted_date: string | null;
}

export interface StatementResult {
  account: Account;
  summary: Summary;
  transactions: Transaction[];
  _reconciliation: Reconciliation | null;
  _anomalies: Anomaly[];
  _skipped_rows: { raw: string; reason: string }[];
  _recurring?: RecurringGroup[];
}

export interface Telemetry {
  total_calls: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_cache_read?: number;
  total_cache_write?: number;
  total_elapsed_s?: number;
  total_cost_usd?: number;
  errors?: string[];
}

export type Decision = "approve" | "reject" | "edit" | "pending";

export interface ReviewItem {
  statementKey: string;
  txIndex: number;
  date: string;
  description: string;
  amount: number;
  side: "deposit" | "withdrawal";
  confidence: number | null;
  reason: string;
}

export interface PipelineEvent {
  event: string;
  data: Record<string, unknown>;
  ts: number;
}
