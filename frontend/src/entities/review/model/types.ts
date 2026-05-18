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
