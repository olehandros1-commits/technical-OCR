import { V1 } from "@/shared/api";
import type { TierInfo } from "../model/types";

export async function listTiers(): Promise<TierInfo[]> {
  const r = await fetch(`${V1}/telemetry/tiers`);
  if (!r.ok) return [];
  const j = await r.json();
  return j.tiers ?? [];
}
