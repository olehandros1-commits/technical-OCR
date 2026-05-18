from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import aiosqlite

from dobs.application.ports.ocr_engine import OcrEnginePort
from dobs.infrastructure.adapters.ocr.file_reader import (
    CorruptDocumentError,
    FileReader,
    IngestError,
    clean_text,
    detect_kind,
)

_OCR_CACHE_PATH = Path(os.getenv("OCR_CACHE_DB", "out/ocr_cache.db"))


async def _file_hash(path: Path) -> str:
    def _sync() -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    return await asyncio.to_thread(_sync)


async def _cache_get(file_hash: str, method: str) -> str | None:
    if not _OCR_CACHE_PATH.exists():
        return None
    try:
        async with aiosqlite.connect(_OCR_CACHE_PATH) as db:
            async with db.execute(
                "SELECT text FROM ocr_cache WHERE file_hash = ? AND method = ?",
                (file_hash, method),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None
    except Exception:
        return None


async def _cache_put(file_hash: str, text: str, method: str) -> None:
    _OCR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_OCR_CACHE_PATH) as db:
        await db.executescript(
            "CREATE TABLE IF NOT EXISTS ocr_cache ("
            "  file_hash  TEXT NOT NULL,"
            "  method     TEXT NOT NULL,"
            "  text       TEXT NOT NULL,"
            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "  PRIMARY KEY (file_hash, method)"
            ");"
        )
        await db.execute(
            "INSERT OR REPLACE INTO ocr_cache (file_hash, method, text) VALUES (?, ?, ?)",
            (file_hash, method, text),
        )
        await db.commit()


def _ocr_one_image(img: object, lang: str, config: str) -> str:
    import pytesseract
    return pytesseract.image_to_string(img, lang=lang, config=config)


class TesseractOcrEngine(OcrEnginePort):
    def __init__(
        self,
        /,
        *,
        file_reader: FileReader,
        cache_path: Path = _OCR_CACHE_PATH,
        lang: str = "eng",
    ) -> None:
        self._file_reader = file_reader
        self._cache_path = cache_path
        self._lang = lang

    async def extract_text(
        self,
        path: str,
        *,
        log_event: Callable | None = None,
    ) -> str:
        p = Path(path)
        if not p.exists():
            raise IngestError(f"File not found: {p}")
        if p.stat().st_size == 0:
            from dobs.infrastructure.adapters.ocr.file_reader import EmptyDocumentError
            raise EmptyDocumentError(f"File is empty: {p}")

        kind = detect_kind(p)

        if kind == "text":
            return await self._file_reader.read(p)
        if kind == "xlsx":
            return await asyncio.to_thread(self._file_reader.from_xlsx, p)
        if kind == "html":
            return await asyncio.to_thread(self._file_reader.from_html, p)
        if kind == "image":
            return await asyncio.to_thread(self._file_reader.from_image, p, self._lang)
        if kind == "pdf":
            return await self._ocr_pdf(p, log_event)

        from dobs.infrastructure.adapters.ocr.file_reader import UnsupportedFormatError
        raise UnsupportedFormatError(
            f"Cannot determine how to read {p.name}. "
            "Supported: PDF, image, xlsx, html, txt."
        )

    async def _ocr_pdf(
        self,
        path: Path,
        log_event: Callable | None = None,
    ) -> str:
        file_hash = await _file_hash(path)
        cached = await _cache_get(file_hash, "tesseract")
        if cached is not None:
            if log_event:
                log_event("ocr_cache_hit", {
                    "file_hash": file_hash[:16], "chars": len(cached), "method": "tesseract",
                })
            return cached
        if log_event:
            log_event("ocr_cache_miss", {"file_hash": file_hash[:16], "method": "tesseract"})

        text = await self._run_tesseract(path, log_event)
        try:
            await _cache_put(file_hash, text, "tesseract")
        except Exception:
            pass
        return text

    async def _run_tesseract(
        self,
        path: Path,
        log_event: Callable | None = None,
    ) -> str:
        try:
            from pdf2image import convert_from_path
            from pdf2image.pdf2image import pdfinfo_from_path
        except ImportError as exc:
            raise IngestError(
                "Tesseract OCR requires `pdf2image` + `pytesseract` + "
                "Tesseract binary. Install with: pip install bank-statement-extractor[ocr]"
            ) from exc

        dpi = int(os.getenv("OCR_DPI", "120"))
        config = os.getenv("OCR_TESSERACT_CONFIG", "--oem 1 --psm 4")

        if log_event:
            log_event("ocr_render_start", {"engine": "tesseract", "dpi": dpi, "config": config})

        t0 = time.time()

        try:
            info = await asyncio.to_thread(pdfinfo_from_path, str(path))
            n_pages = int(info.get("Pages", 0))
        except Exception:
            n_pages = 0

        n_workers = max(1, min(int(os.getenv("OCR_WORKERS", "8")), n_pages or 8))
        if log_event:
            log_event("ocr_pool_start", {"pages": n_pages or "?", "workers": n_workers})

        results: dict[int, str] = {}
        t_ocr = time.time()

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = []
            for page_idx in range(1, (n_pages or 1) + 1):
                try:
                    imgs = await asyncio.to_thread(
                        convert_from_path,
                        str(path),
                        dpi,
                        first_page=page_idx,
                        last_page=page_idx,
                    )
                except Exception as e:
                    if page_idx == 1:
                        raise CorruptDocumentError(f"PDF rasterisation failed: {e}") from e
                    break
                if not imgs:
                    break
                fut = loop.run_in_executor(pool, _ocr_one_image, imgs[0], self._lang, config)
                futures.append((page_idx - 1, fut))

        if log_event:
            log_event("ocr_render_done", {
                "pages": len(futures),
                "elapsed_s": round(time.time() - t0, 2),
            })

        page_texts = await asyncio.gather(*(f for _, f in futures))
        for (idx, _), text in zip(futures, page_texts):
            results[idx] = text
            completed = idx + 1
            if log_event and (completed % 5 == 0 or completed == len(futures)):
                log_event("ocr_page", {
                    "done": completed,
                    "of": len(futures),
                    "elapsed_s": round(time.time() - t_ocr, 1),
                })

        if log_event:
            log_event("ocr_pool_done", {
                "pages": len(results),
                "elapsed_s": round(time.time() - t_ocr, 2),
            })

        return clean_text("\n".join(results[i] for i in sorted(results)))
