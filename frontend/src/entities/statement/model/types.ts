import type { Reconciliation } from "../../reconciliation/model/types";
import type { Anomaly } from "../../anomaly/model/types";
import type { Transaction } from "../../transaction/model/types";
import type { RecurringGroup } from "../../recurring-group/model/types";

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

export interface StatementResult {
  account: Account;
  summary: Summary;
  transactions: Transaction[];
  _reconciliation: Reconciliation | null;
  _anomalies: Anomaly[];
  _skipped_rows: { raw: string; reason: string }[];
  _recurring?: RecurringGroup[];
}
