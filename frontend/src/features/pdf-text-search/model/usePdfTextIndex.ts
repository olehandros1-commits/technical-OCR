import { useCallback, useEffect, useRef } from "react";
import { pdfjs } from "react-pdf";

export function usePdfTextIndex(url: string | null, numPages: number) {
  const pageTextsRef = useRef<string[]>([]);
  const indexingRef = useRef(false);

  useEffect(() => {
    pageTextsRef.current = [];
    indexingRef.current = false;
  }, [url]);

  const buildIndex = useCallback(async (pdfUrl: string, total: number) => {
    if (indexingRef.current) return;
    indexingRef.current = true;
    const doc = await pdfjs.getDocument(pdfUrl).promise;
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

  return pageTextsRef;
}
