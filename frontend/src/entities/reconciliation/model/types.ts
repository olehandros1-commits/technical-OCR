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
