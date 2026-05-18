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

export type { ExtractOptions } from "./base";
