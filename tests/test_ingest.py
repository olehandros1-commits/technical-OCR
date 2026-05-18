"""Tests for ingest format detection and typed errors."""
from pathlib import Path

import pytest

from extractor.ingest import (
    ingest, clean_text,
    EmptyDocumentError, UnsupportedFormatError, IngestError,
)


def test_clean_text_strips_notion_noise():
    raw = "17.05.2026, 22:08\n\nhttps://file.notion.so/abc?x=1\n\nReal content\n\n1/210\n"
    cleaned = clean_text(raw)
    assert "Real content" in cleaned
    assert "notion" not in cleaned.lower()
    assert "1/210" not in cleaned


def test_clean_text_strips_azure_markers():
    raw = "Apr 01 SOMETHING :unselected: 100.00\nApr 02 OTHER :selected: 200.00"
    assert ":unselected:" not in clean_text(raw)
    assert ":selected:" not in clean_text(raw)
    assert "SOMETHING" in clean_text(raw)


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(IngestError):
        ingest(str(tmp_path / "nope.pdf"))


def test_empty_file_raises(tmp_path: Path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    with pytest.raises(EmptyDocumentError):
        ingest(str(p))


def test_unknown_format_raises(tmp_path: Path):
    p = tmp_path / "weird.bin"
    p.write_bytes(b"\x01\x02\x03\x04\xff\xfe")
    with pytest.raises((UnsupportedFormatError, IngestError)):
        ingest(str(p))


def test_text_file_passthrough(tmp_path: Path):
    p = tmp_path / "data.txt"
    p.write_text("Apr 01 SOMETHING 100.00\nBeginning Balance as of 04/01/2025\n",
                 encoding="utf-8")
    out = ingest(str(p))
    assert "SOMETHING" in out
