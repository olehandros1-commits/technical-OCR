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
