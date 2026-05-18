export type TxCategory =
  | "ACH_PAYABLE" | "WIRE" | "CHECK" | "DEPOSIT_REMOTE" | "DEPOSIT_CASH"
  | "TRANSFER_INTERNAL" | "PAYROLL" | "VENDOR_PAYMENT" | "CARD_PAYMENT"
  | "LOAN_PAYMENT" | "INTEREST" | "FEE" | "TAX" | "OTHER";

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
