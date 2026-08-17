"""Clerk session verification for the resolver -- deliberately duplicated
in archive/utils/clerk_auth.py (same reasoning as this app's other
cross-service duplication, e.g. archive/static/style.css's own header
comment) rather than shared, since the two services have independent
deploys and dependency sets.

Chosen 2026-08-10 specifically so this app never has to hand-roll
session/cookie/password security -- see BACKLOG.md's "Accounts + token
billing" section for the fuller reasoning and the internal-auth design
this superseded.
"""

import base64
import logging
import os
from typing import Optional

from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import Request

logger = logging.getLogger("rtr_deeplink.clerk")


def clerk_frontend_api_url(publishable_key: str) -> Optional[str]:
    """Derives Clerk's per-account "Frontend API" domain from a
    pk_test_.../pk_live_... publishable key, so the ClerkJS CDN script
    tags (see base.html) can be built without asking the user to
    hand-copy a personalized snippet from Clerk's dashboard. Matches
    Clerk's own @clerk/shared parsePublishableKey exactly: the segment
    after the second underscore is base64, decoding to "{domain}$" --
    strip the trailing "$". Returns None on anything malformed (also
    covers publishable_key == "", i.e. Clerk not configured at all).

    Real incident, 2026-08-11: Clerk's actual publishable keys omit
    trailing "=" padding, so b64decode() only worked by coincidence
    whenever a given key's encoded segment happened to already be a
    multiple of 4 characters long -- true for the dev-instance key this
    was first tested against, false for the production key, which
    silently broke Clerk site-wide in production (empty FAPI URL ->
    shared_static/clerk_nav.js's own guard disables everything) until
    caught by comparing the live site's rendered attribute against what
    was expected. Re-padding before decoding fixes both.
    """
    try:
        _, _, encoded = publishable_key.split("_", 2)
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.b64decode(padded).decode()
        if not decoded.endswith("$"):
            return None
        return decoded[:-1]
    except Exception:
        return None


# Clerk's authorized_parties check rejects a session token issued for a
# different origin/app being replayed against this one. Falls back to
# common local-dev origins when PUBLIC_BASE_URL isn't set, so this still
# works against a real Clerk *development* instance (which has no DNS/
# domain restriction of its own) during local testing.
_LOCAL_DEV_ORIGINS = ["http://localhost:8010", "http://127.0.0.1:8010"]


def _authorized_parties() -> list:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return [base] if base else _LOCAL_DEV_ORIGINS


def get_clerk_user_id(request: Request) -> Optional[str]:
    """Verifies the visitor's Clerk session and returns their Clerk user
    id (e.g. "user_2abc...") if signed in, else None.

    Returns None -- fast, no side effects, never raises -- for every
    anonymous visitor and whenever Clerk isn't configured at all (no
    CLERK_SECRET_KEY set), so accounts features degrade to "everyone
    looks logged out" rather than ever breaking a page for a signed-out
    visitor or when Clerk itself is down. authenticate_request() already
    short-circuits internally with no verification work at all when
    there's no session cookie/Authorization header present, so anonymous
    traffic pays essentially nothing extra either way.

    Verification is local (no network call) once clerk-backend-api's own
    internal JWKS cache is warm; setting CLERK_JWT_KEY (optional, see
    .env.example) makes it networkless from the very first request
    instead of just after a one-time per-signing-key fetch.
    """
    secret_key = os.environ.get("CLERK_SECRET_KEY", "")
    if not secret_key:
        return None

    try:
        options = AuthenticateRequestOptions(
            secret_key=secret_key,
            jwt_key=os.environ.get("CLERK_JWT_KEY") or None,
            authorized_parties=_authorized_parties(),
        )
        state = authenticate_request(request, options)
    except Exception:
        logger.exception("Clerk session verification failed unexpectedly.")
        return None

    if not state.is_signed_in or not state.payload:
        # See archive/utils/clerk_auth.py's matching comment -- only
        # logged when a real session cookie was present but verification
        # still failed (added 2026-08-11 to debug a real production case
        # with no other visible signal).
        if "__session" in request.cookies:
            logger.warning(
                "Clerk session cookie present but verification failed: %s",
                getattr(state, "message", None) or getattr(state, "reason", None),
            )
        return None
    return state.payload.get("sub")
