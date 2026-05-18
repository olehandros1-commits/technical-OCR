"""Tests for the tier catalog + env application."""
import os

from extractor.tiers import (
    PREMIUM, BALANCED, LOCAL, CHEAP,
    all_tiers, get_tier, apply_tier_env,
)


def test_catalog_has_four_tiers():
    names = [t.name for t in all_tiers()]
    assert set(names) == {"premium", "balanced", "local", "cheap"}


def test_get_tier_default_is_balanced():
    # Unset env, no arg -> balanced.
    os.environ.pop("EXTRACTOR_TIER", None)
    assert get_tier().name == "balanced"


def test_get_tier_env_override():
    os.environ["EXTRACTOR_TIER"] = "premium"
    try:
        assert get_tier().name == "premium"
    finally:
        os.environ.pop("EXTRACTOR_TIER", None)


def test_get_tier_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        get_tier("nonsense")


def test_apply_tier_env_anthropic_keys():
    apply_tier_env(PREMIUM)
    assert os.environ["EXTRACTOR_BACKEND"] == "anthropic"
    assert os.environ["ANTHROPIC_MODEL_REPAIR"] == PREMIUM.model_repair
    assert "opus" in os.environ["ANTHROPIC_MODEL_REPAIR"]


def test_apply_tier_env_ollama_keys():
    apply_tier_env(LOCAL)
    assert os.environ["EXTRACTOR_BACKEND"] == "ollama"
    assert os.environ["OLLAMA_MODEL_EXTRACT"] == LOCAL.model_extract
    assert "qwen" in os.environ["OLLAMA_MODEL_EXTRACT"]


def test_each_tier_carries_cost_estimate():
    for t in all_tiers():
        low, high = t.expected_cost_usd
        assert low <= high
        assert low >= 0


def test_cheap_tier_under_dollar_low_end():
    assert CHEAP.expected_cost_usd[0] < 1.0
    assert BALANCED.expected_cost_usd[0] < PREMIUM.expected_cost_usd[0]
