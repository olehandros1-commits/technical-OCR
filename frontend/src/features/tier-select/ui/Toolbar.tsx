import { useEffect, useState } from "react";
import { listTiers } from "@/entities/tier";
import type { Backend, OcrMode, Tier, TierInfo } from "@/entities/tier";

interface Props {
  backend: Backend;
  setBackend: (b: Backend) => void;
  tier: Tier | "";
  setTier: (t: Tier | "") => void;
  ocrMode: OcrMode;
  setOcrMode: (m: OcrMode) => void;
  enrich: boolean;
  setEnrich: (b: boolean) => void;
  parallel: number;
  setParallel: (n: number) => void;
}

export function Toolbar(p: Props) {
  const [tiers, setTiers] = useState<TierInfo[]>([]);

  useEffect(() => {
    listTiers().then(setTiers).catch(() => setTiers([]));
  }, []);

  const activeTier = tiers.find((t) => t.name === p.tier) ?? null;

  return (
    <div className="toolbar">
      <label>
        <span>Tier</span>
        <select
          value={p.tier}
          onChange={(e) => p.setTier((e.target.value as Tier) || "")}
        >
          <option value="">— custom —</option>
          {tiers.map((t) => (
            <option key={t.name} value={t.name}>
              {t.display}  ·  ~${t.expected_cost_usd[0].toFixed(2)}–$
              {t.expected_cost_usd[1].toFixed(2)} / 10 stmt
            </option>
          ))}
        </select>
      </label>
      {activeTier && (
        <span className="tier-blurb" title={activeTier.description}>
          {activeTier.description.slice(0, 80)}
          {activeTier.description.length > 80 ? "…" : ""}
        </span>
      )}
      <label>
        <span>Backend</span>
        <select
          value={p.backend}
          onChange={(e) => p.setBackend(e.target.value as Backend)}
          disabled={!!p.tier}
          title={p.tier ? "Tier controls the backend" : ""}
        >
          <option value="anthropic">Claude (cloud)</option>
          <option value="ollama">qwen2.5 (local Ollama)</option>
        </select>
      </label>
      <label>
        <span>OCR mode</span>
        <select
          value={p.ocrMode}
          onChange={(e) => p.setOcrMode(e.target.value as OcrMode)}
        >
          <option value="auto">auto (text first, Tesseract fallback)</option>
          <option value="vision">vision LLM</option>
          <option value="tesseract">Tesseract</option>
          <option value="skip">skip (text-PDF only)</option>
        </select>
      </label>
      <label>
        <input
          type="checkbox"
          checked={p.enrich}
          onChange={(e) => p.setEnrich(e.target.checked)}
        />
        <span>Enrich (categories + confidence)</span>
      </label>
      <label>
        <span>Parallel</span>
        <input
          type="number"
          min={1}
          max={8}
          value={p.parallel}
          onChange={(e) => p.setParallel(Number(e.target.value))}
        />
      </label>
    </div>
  );
}
