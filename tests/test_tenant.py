"""Tests for the tenant isolation primitive."""
from extractor.tenant import (
    normalise_tenant, current_tenant, tenant_scope, scoped_key,
)


def test_default_when_unset():
    assert current_tenant() == "_default"
    assert scoped_key("k").startswith("_default::")


def test_normalise_rejects_traversal_attempts():
    assert normalise_tenant("../etc/passwd") == "_default"
    assert normalise_tenant("good-id_42") == "good-id_42"
    assert normalise_tenant("") == "_default"
    assert normalise_tenant(None) == "_default"


def test_scope_binds_and_unbinds():
    with tenant_scope("acme"):
        assert current_tenant() == "acme"
        assert scoped_key("k") == "acme::k"
    assert current_tenant() == "_default"


def test_scopes_nest_correctly():
    with tenant_scope("outer"):
        assert current_tenant() == "outer"
        with tenant_scope("inner"):
            assert current_tenant() == "inner"
        assert current_tenant() == "outer"
    assert current_tenant() == "_default"
