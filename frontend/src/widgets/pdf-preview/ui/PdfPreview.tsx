import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc =
  `https://cdn.jsdelivr.net/npm/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface Props {
  file: File | null;
  targetText?: string | null;
}

function normalise(s: string): string {
  return s.toUpperCase().replace(/\s+/g, " ").trim();
}

function tryMatch(pageText: string, target: string): boolean {
  const n = normalise(pageText);
  const candidates = [
    normalise(target).slice(0, 60),
    normalise(target).slice(0, 30),
    normalise(target).slice(0, 20),
  ];
  return candidates.some((c) => c.length >= 4 && n.includes(c));
}

export function PdfPreview({ file, targetText }: Props) {
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(0.9);
  const [toast, setToast] = useState<string | null>(null);

  const pageTextsRef = useRef<string[]>([]);
  const indexingRef = useRef(false);
  const pageRef = useRef<HTMLDivElement | null>(null);
  const highlightCleanupRef = useRef<(() => void) | null>(null);

  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => {
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [url]);

  useEffect(() => {
    pageTextsRef.current = [];
    indexingRef.current = false;
  }, [url]);

  const buildIndex = useCallback(async (pdfUrl: string, total: number) => {
    if (indexingRef.current) return;
    indexingRef.current = true;
    const pdfjsLib = pdfjs;
    const doc = await pdfjsLib.getDocument(pdfUrl).promise;
    const texts: string[] = [];
    for (let i = 1; i <= total; i++) {
      const pg = await doc.getPage(i);
      const content = await pg.getTextContent();
      texts.push(content.items.map((it) => ("str" in it ? it.str : "")).join(" "));
    }
    pageTextsRef.current = texts;
  }, []);

  useEffect(() => {
    if (!url || numPages === 0) return;
    buildIndex(url, numPages);
  }, [url, numPages, buildIndex]);

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
  }, []);

  useEffect(() => {
    if (highlightCleanupRef.current) {
      highlightCleanupRef.current();
      highlightCleanupRef.current = null;
    }
  }, [page]);

  useEffect(() => {
    if (!targetText || !url) return;
    const texts = pageTextsRef.current;
    if (texts.length === 0) {
      setToast("PDF index not ready yet — try again in a moment.");
      setTimeout(() => setToast(null), 3000);
      return;
    }
    const found = texts.findIndex((t) => tryMatch(t, targetText));
    if (found === -1) {
      setToast("Couldn't locate this row in the PDF.");
      setTimeout(() => setToast(null), 3000);
      return;
    }
    setPage(found + 1);
  }, [targetText, url]);

  useEffect(() => {
    if (!targetText) return;
    const id = setTimeout(() => applyHighlight(targetText), 300);
    return () => clearTimeout(id);
  }, [page, targetText, applyHighlight]);

  if (!file || !url) return null;

  return (
    <aside className="pdf-preview">
      <div className="pdf-toolbar">
        <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>‹</button>
        <span className="pdf-pos">page {page} / {numPages || "?"}</span>
        <button onClick={() => setPage(p => Math.min(numPages || p + 1, p + 1))}
                disabled={page >= numPages}>›</button>
        <span className="pdf-spacer" />
        <button onClick={() => setScale(s => Math.max(0.4, s - 0.1))}>-</button>
        <span className="pdf-zoom">{Math.round(scale * 100)}%</span>
        <button onClick={() => setScale(s => Math.min(2.0, s + 0.1))}>+</button>
      </div>
      {toast && <div className="pdf-toast">{toast}</div>}
      <div className="pdf-frame">
        <div ref={pageRef}>
          <Document
            file={url}
            onLoadSuccess={(pdf) => setNumPages(pdf.numPages)}
            onLoadError={(err) => console.error("pdf load error", err)}
            loading={<div className="pdf-loading">Loading PDF…</div>}
            error={<div className="pdf-error">Couldn't render PDF preview (this is just visual; extraction still works).</div>}
          >
            <Page
              pageNumber={page}
              scale={scale}
              renderTextLayer
              renderAnnotationLayer={false}
            />
          </Document>
        </div>
      </div>
    </aside>
  );
}
