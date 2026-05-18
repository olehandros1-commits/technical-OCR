import { useCallback, useEffect, useRef } from "react";

function normalise(s: string): string {
  return s.toUpperCase().replace(/\s+/g, " ").trim();
}

export function tryMatch(pageText: string, target: string): boolean {
  const n = normalise(pageText);
  const candidates = [
    normalise(target).slice(0, 60),
    normalise(target).slice(0, 30),
    normalise(target).slice(0, 20),
  ];
  return candidates.some((c) => c.length >= 4 && n.includes(c));
}

export function usePdfHighlight(
  pageRef: React.RefObject<HTMLDivElement | null>,
  page: number,
) {
  const highlightCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (highlightCleanupRef.current) {
      highlightCleanupRef.current();
      highlightCleanupRef.current = null;
    }
  }, [page]);

  const applyHighlight = useCallback((target: string) => {
    if (highlightCleanupRef.current) {
      highlightCleanupRef.current();
      highlightCleanupRef.current = null;
    }
    if (!pageRef.current || !target) return;
    const norm = normalise(target).slice(0, 60);
    const spans = Array.from(
      pageRef.current.querySelectorAll<HTMLSpanElement>(
        ".react-pdf__Page__textContent span",
      ),
    );
    const applied: HTMLSpanElement[] = [];
    for (const span of spans) {
      if (normalise(span.textContent ?? "").length < 3) continue;
      if (norm.includes(normalise(span.textContent ?? "").slice(0, 20))) {
        span.classList.add("pdf-highlight");
        applied.push(span);
      }
    }
    highlightCleanupRef.current = () => {
      for (const s of applied) s.classList.remove("pdf-highlight");
    };
  }, [pageRef]);

  return applyHighlight;
}
