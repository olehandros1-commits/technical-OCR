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
  expected_cost_usd: [number, number];
  enrich_default: boolean;
  ocr_mode: OcrMode;
}
