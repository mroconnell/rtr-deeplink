"""Unit tests for app/utils/clerk_auth.py and archive/utils/clerk_auth.py
-- both modules are deliberately identical (see their own docstrings), so
this file exercises both to catch either one drifting out of sync.
"""

import base64

import pytest
from starlette.requests import Request

import app.utils.clerk_auth as resolver_clerk_auth
import archive.utils.clerk_auth as archive_clerk_auth

MODULES = [resolver_clerk_auth, archive_clerk_auth]


def _fake_publishable_key(domain: str) -> str:
    encoded = base64.b64encode(f"{domain}$".encode()).decode()
    return f"pk_test_{encoded}"


def _request(headers: list = None) -> Request:
    scope = {"type": "http", "headers": headers or [], "method": "GET", "path": "/"}
    return Request(scope)


@pytest.mark.parametrize("mod", MODULES)
def test_clerk_frontend_api_url_decodes_a_real_shaped_key(mod):
    key = _fake_publishable_key("some-app-12.clerk.accounts.dev")
    assert mod.clerk_frontend_api_url(key) == "some-app-12.clerk.accounts.dev"


@pytest.mark.parametrize("mod", MODULES)
def test_clerk_frontend_api_url_decodes_unpadded_key(mod):
    # Real incident, 2026-08-11: Clerk's actual keys omit base64's trailing
    # "=" padding, so b64decode() only worked before by coincidence -- only
    # when a key's encoded segment happened to already be a multiple of 4
    # characters. "some-app-12.clerk.accounts.dev$" (33 bytes) -> 44
    # padded base64 chars (a multiple of 4, no bug exposed); this repo's
    # real production key's domain segment needed real padding and broke
    # site-wide in production before this fix. Exercises the exact
    # production key value, unpadded, the way Clerk actually issues it --
    # not a helper-encoded (thus always-correctly-padded) fake.
    key = "pk_live_Y2xlcmsucmVkdGFwZXJlY29yZGluZ3MuY29tJA"
    assert mod.clerk_frontend_api_url(key) == "clerk.redtaperecordings.com"


@pytest.mark.parametrize("mod", MODULES)
def test_clerk_frontend_api_url_returns_none_for_empty_key(mod):
    assert mod.clerk_frontend_api_url("") is None


@pytest.mark.parametrize("mod", MODULES)
def test_clerk_frontend_api_url_returns_none_for_malformed_key(mod):
    assert mod.clerk_frontend_api_url("not-a-real-key") is None
    assert mod.clerk_frontend_api_url("pk_test_not-valid-base64!!!") is None


@pytest.mark.parametrize("mod", MODULES)
def test_clerk_frontend_api_url_returns_none_when_decoded_lacks_dollar_sign(mod):
    # A syntactically-valid base64 payload that just doesn't end in "$" --
    # confirms the validation step, not just that decoding didn't crash.
    encoded = base64.b64encode(b"no-trailing-dollar-sign").decode()
    assert mod.clerk_frontend_api_url(f"pk_test_{encoded}") is None


@pytest.mark.parametrize("mod", MODULES)
def test_get_clerk_user_id_returns_none_when_unconfigured(mod, monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    assert mod.get_clerk_user_id(_request()) is None


@pytest.mark.parametrize("mod", MODULES)
def test_get_clerk_user_id_returns_none_with_no_session_cookie(mod, monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake_for_this_test")
    # No Cookie/Authorization header at all -- authenticate_request()
    # itself short-circuits to signed-out with zero verification work.
    assert mod.get_clerk_user_id(_request()) is None


@pytest.mark.parametrize("mod", MODULES)
def test_get_clerk_user_id_never_raises_on_garbage_cookie(mod, monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake_for_this_test")
    req = _request(headers=[(b"cookie", b"__session=not-a-real-jwt-at-all")])
    # Should fail verification cleanly and return None, not raise.
    assert mod.get_clerk_user_id(req) is None
