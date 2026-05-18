"""Tests for vendor_lookup.

We don't hit the live Clearbit endpoint in tests -- the env switch
VENDOR_DISABLE_CLEARBIT=1 makes the lookup return None and fall
through to the stub, which is exactly what unit tests need.
"""
import json
import os

import pytest

from extractor import vendor_lookup as vl


@pytest.fixture(autouse=True)
def disable_clearbit(monkeypatch):
    monkeypatch.setenv("VENDOR_DISABLE_CLEARBIT", "1")
    # Use a temp cache file per test to avoid cross-test pollution.
    yield


def test_stub_when_nothing_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "_CACHE_PATH", tmp_path / "vc.db")
    monkeypatch.setattr(vl, "_SEEDS_CACHE", {})  # no seeds either
    info = vl.lookup_vendor("Random Company XYZ")
    assert info.source == "stub"
    assert info.canonical_name == "Random Company Xyz"


def test_seed_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "_CACHE_PATH", tmp_path / "vc.db")
    monkeypatch.setattr(vl, "_SEEDS_CACHE", {
        "acme corp": {"name": "Acme Corp", "domain": "acme.com",
                      "logo_url": "https://logo.clearbit.com/acme.com"},
    })
    info = vl.lookup_vendor("Acme Corp")
    assert info.source == "seed"
    assert info.canonical_name == "Acme Corp"
    assert info.domain == "acme.com"


def test_seed_fuzzy_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "_CACHE_PATH", tmp_path / "vc.db")
    monkeypatch.setattr(vl, "_SEEDS_CACHE", {
        "genuine parts": {"name": "Genuine Parts Co", "domain": "genpt.com"},
    })
    info = vl.lookup_vendor("GENUINE PARTS CO/ACH")
    assert info.source == "seed"
    assert info.domain == "genpt.com"


def test_cache_hits_skip_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "_CACHE_PATH", tmp_path / "vc.db")
    monkeypatch.setattr(vl, "_SEEDS_CACHE", {
        "acme": {"name": "Acme", "domain": "acme.com"},
    })
    info1 = vl.lookup_vendor("Acme")
    info2 = vl.lookup_vendor("Acme")
    assert info1.canonical_name == info2.canonical_name
    # Persisted to sqlite -- file exists now.
    assert (tmp_path / "vc.db").exists()


def test_enrich_vendors_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "_CACHE_PATH", tmp_path / "vc.db")
    monkeypatch.setattr(vl, "_SEEDS_CACHE", {
        "acme": {"name": "Acme Corp", "domain": "acme.com",
                 "logo_url": "https://logo.clearbit.com/acme.com"},
    })
    txns = [
        {"date": "2025-04-01", "description": "X", "vendor": "Acme"},
        {"date": "2025-04-02", "description": "Y", "vendor": "Unknown Vendor"},
        {"date": "2025-04-03", "description": "Z", "vendor": None},
    ]
    n = vl.enrich_vendors_in_place(txns)
    assert n == 1
    assert txns[0]["_vendor_logo"].startswith("https://")
    assert "_vendor_logo" not in txns[1]
    assert "_vendor_logo" not in txns[2]


def test_empty_vendor_returns_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "_CACHE_PATH", tmp_path / "vc.db")
    info = vl.lookup_vendor("")
    assert info.source == "stub"
    assert info.canonical_name == ""


def test_normalise_key_collapses_whitespace_and_lowercases():
    # _normalise_key keeps punctuation but collapses spaces and lowercases.
    assert vl._normalise_key("  Acme  CORP/INC.  ") == "acme corp/inc."
