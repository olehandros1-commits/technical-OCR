from dobs.infrastructure.adapters.tenant.context_tenant import ContextTenantBinder, _normalise


def test_default_when_unset():
    binder = ContextTenantBinder()
    assert binder.current() == "_default"
    assert binder.scoped_key("k").startswith("_default::")


def test_normalise_rejects_traversal_attempts():
    assert _normalise("../etc/passwd") == "_default"
    assert _normalise("good-id_42") == "good-id_42"
    assert _normalise("") == "_default"
    assert _normalise(None) == "_default"


async def test_scope_binds_and_unbinds():
    binder = ContextTenantBinder()
    async with binder.tenant_scope("acme"):
        assert binder.current() == "acme"
        assert binder.scoped_key("k") == "acme::k"
    assert binder.current() == "_default"


async def test_scopes_nest_correctly():
    binder = ContextTenantBinder()
    async with binder.tenant_scope("outer"):
        assert binder.current() == "outer"
        async with binder.tenant_scope("inner"):
            assert binder.current() == "inner"
        assert binder.current() == "outer"
    assert binder.current() == "_default"
