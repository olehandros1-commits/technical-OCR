"""Vision-LLM OCR ingest -- the high-accuracy alternative to Tesseract.

For scanned PDFs, we render each page as a PNG and feed batches of pages to
a vision-capable LLM (Claude Sonnet via AnthropicBackend.call_vision, or
llama3.2-vision via OllamaBackend.call_vision). The model returns the page
text faithfully, including columnar tables and partially-redacted fields,
which OCR engines like Tesseract often mangle.

Trade-offs vs Tesseract:
  * Vision LLM: better on tables, columns, low-contrast scans, and pages
    with hand-marked redactions. Slower and more expensive.
  * Tesseract: free, instant, fine for typed text without complex layout.

Architecture: this is an alternate ingest path. The pipeline doesn't care
which OCR it gets; it just receives cleaned text. To swap in a third
backend (Azure DI, AWS Textract, Mistral OCR, etc.), implement
`from_pdf_<name>(path) -> str` and register it.
"""
from __future__ import annotations
import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Iterable
from pydantic import BaseModel, ConfigDict

from extractor.backends import LLMBackend
from extractor.backends.base import ImagePart

log = logging.getLogger(__name__)


class _PageText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_text: str


_SYSTEM = """You are a high-fidelity OCR system for bank statements.

You will receive one or more page images. For each image, transcribe the
text exactly as it appears, preserving:
  * Date columns and amount columns in their original order.
  * Tables: emit row-by-row using simple spaces or | as separators.
  * Section headers ("MISCELLANEOUS DEBITS & CREDITS", "CHECKS PAID", etc.)
    on their own line.
  * Currency symbols and commas in numbers.

DO NOT:
  * paraphrase or summarise.
  * skip redacted blocks -- represent them as [REDACTED].
  * invent text that isn't visible.
  * add commentary or headers.

If multiple pages are sent, concatenate them with a single blank line
between pages.

Return the result via the JSON schema with the full transcription in the
`page_text` field."""


def _pdf_pages_to_images(pdf_path: str | Path, dpi: int = 200) -> list[bytes]:
    """Render every PDF page to a PNG, return raw bytes per page."""
    from pdf2image import convert_from_path

    images = convert_from_path(str(pdf_path), dpi=dpi)
    out: list[bytes] = []
    for img in images:
        buf = BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


def _to_image_part(png_bytes: bytes) -> ImagePart:
    return ImagePart(
        mime_type="image/png",
        data_b64=base64.b64encode(png_bytes).decode("ascii"),
    )


def _batches(items: list, n: int) -> Iterable[list]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def from_pdf_vision(
    pdf_path: str | Path,
    backend: LLMBackend,
    *,
    dpi: int = 200,
    pages_per_call: int = 3,
) -> str:
    """OCR a PDF using a vision-capable LLM. Returns combined text."""
    if not backend.supports_vision():
        raise RuntimeError(
            f"Backend '{backend.name}' does not support vision; "
            "use a vision-capable backend (e.g. AnthropicBackend) for this path."
        )

    pages = _pdf_pages_to_images(pdf_path, dpi=dpi)
    log.info("vision-OCR: %d pages, batching %d per call", len(pages), pages_per_call)

    transcripts: list[str] = []
    for i, batch in enumerate(_batches(pages, pages_per_call)):
        images = [_to_image_part(b) for b in batch]
        user = (
            f"Transcribe these {len(batch)} bank statement page(s). "
            "Return the JSON object with the full transcription."
        )
        resp = backend.call_vision(
            system=_SYSTEM,
            user=user,
            images=images,
            response_model=_PageText,
        )
        transcripts.append(resp.page_text)
        log.info("vision-OCR: batch %d done (%d chars)", i + 1, len(resp.page_text))

    return "\n\n".join(transcripts)
