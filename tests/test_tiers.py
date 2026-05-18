import os
import pytest

from dobs.application.config import PREMIUM, BALANCED, LOCAL, CHEAP, TierRegistry


def test_catalog_has_four_tiers():
    names = [t.name for t in TierRegistry.all_tiers()]
    assert set(names) == {"premium", "balanced", "local", "cheap"}


def test_get_tier_by_name():
    assert TierRegistry.tier_by_name("balanced").name == "balanced"


def test_get_tier_unknown_raises():
    with pytest.raises(ValueError):
        TierRegistry.tier_by_name("nonsense")


def test_premium_tier_uses_anthropic():
    assert PREMIUM.backend == "anthropic"
    assert "opus" in PREMIUM.model_repair


def test_local_tier_uses_ollama():
    assert LOCAL.backend == "ollama"
    assert "qwen" in LOCAL.model_extract


def test_each_tier_carries_cost_estimate():
    for t in TierRegistry.all_tiers():
        low, high = t.expected_cost_usd
        assert low <= high
        assert low >= 0


def test_cheap_tier_under_dollar_low_end():
    assert CHEAP.expected_cost_usd[0] < 1.0
    assert BALANCED.expected_cost_usd[0] < PREMIUM.expected_cost_usd[0]
