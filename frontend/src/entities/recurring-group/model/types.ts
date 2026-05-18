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
