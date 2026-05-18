import json
import os
from pathlib import Path

import pytest

from dobs.infrastructure.adapters.vendor.seed_lookup import SeedVendorLookup, _normalise_key
from dobs.infrastructure.adapters.vendor.clearbit_lookup import ClearbitVendorLookup
from dobs.infrastructure.adapters.vendor.composite_lookup import CompositeVendorLookup


@pytest.fixture(autouse=True)
def disable_clearbit(monkeypatch):
    monkeypatch.setenv("VENDOR_DISABLE_CLEARBIT", "1")
    yield


def _seed_lookup_with_data(tmp_path: Path, seeds: dict) -> SeedVendorLookup:
    seeds_file = tmp_path / "seeds.json"
    seeds_file.write_text(json.dumps(seeds), encoding="utf-8")
    return SeedVendorLookup(seeds_path=seeds_file)


async def test_stub_when_nothing_matches(tmp_path):
    lookup = _seed_lookup_with_data(tmp_path, {})
    info = await lookup.lookup("Random Company XYZ")
    assert info.canonical_name is None


async def test_seed_lookup(tmp_path):
    lookup = _seed_lookup_with_data(tmp_path, {
        "Acme Corp": {"name": "Acme Corp", "logo_url": "https://logo.clearbit.com/acme.com"},
    })
    info = await lookup.lookup("Acme Corp")
    assert info.canonical_name == "Acme Corp"
    assert info.logo_url == "https://logo.clearbit.com/acme.com"


async def test_seed_fuzzy_prefix(tmp_path):
    lookup = _seed_lookup_with_data(tmp_path, {
        "Genuine Parts": {"name": "Genuine Parts Co"},
    })
    info = await lookup.lookup("GENUINE PARTS CO/ACH")
    assert info.canonical_name == "Genuine Parts Co"


async def test_seed_returns_none_for_unmatched(tmp_path):
    lookup = _seed_lookup_with_data(tmp_path, {
        "acme": {"name": "Acme", "logo_url": "https://logo.clearbit.com/acme.com"},
    })
    info1 = await lookup.lookup("Acme")
    info2 = await lookup.lookup("Acme")
    assert info1.canonical_name == info2.canonical_name


async def test_empty_vendor_returns_none_name(tmp_path):
    lookup = _seed_lookup_with_data(tmp_path, {})
    info = await lookup.lookup("")
    assert info.canonical_name is None


def test_normalise_key_collapses_whitespace_and_lowercases():
    assert _normalise_key("  Acme  CORP/INC.  ") == "acme corp/inc."
