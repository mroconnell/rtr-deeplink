"""Clerk session verification for the Archive service -- deliberately
duplicated in app/utils/clerk_auth.py (same reasoning as this app's other
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

logger = logging.getLogger("rtr_archive.clerk")


def clerk_frontend_api_url(publishable_key: str) -> Optional[str]:
    """See app/utils/clerk_auth.py's matching function -- identical here,
    deliberately duplicated rather than shared (same reasoning as the rest
    of this module). Includes that function's 2026-08-11 base64-padding
    fix (Clerk's real keys omit trailing "=" padding)."""
    try:
        _, _, encoded = publishable_key.split("_", 2)
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.b64decode(padded).decode()
        if not decoded.endswith("$"):
            return None
        return decoded[:-1]
    except Exception:
        return None


# Local-dev fallback origins for Clerk's authorized_parties check. Always
# the *resolver's* local port, not this service's own -- a real browser
# only ever talks to Archive by way of the resolver's reverse proxy
# (redtaperecordings.com/meetings, /m/*), so that's the origin Clerk
# actually issued the session token for, even when this service is the
# one doing the verifying.
_LOCAL_DEV_ORIGINS = ["http://localhost:8010", "http://127.0.0.1:8010"]


def _authorized_parties() -> list:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    return [base] if base else _LOCAL_DEV_ORIGINS


def get_clerk_user_id(request: Request) -> Optional[str]:
    """Verifies the visitor's Clerk session (forwarded through the
    resolver's reverse proxy, see app/archive_client.py's proxy_get())
    and returns their Clerk user id if signed in, else None.

    Returns None -- fast, no side effects, never raises -- for every
    anonymous visitor and whenever Clerk isn't configured at all, so
    accounts features degrade to "everyone looks logged out" rather than
    ever breaking a page. See app/utils/clerk_auth.py's matching
    docstring for the full reasoning (identical here).
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
        # Only worth logging when a real session cookie was actually
        # present -- the overwhelmingly common case (a plain anonymous
        # visitor, no cookie at all) stays silent, matching this
        # function's "anonymous traffic pays nothing" design. When a
        # cookie WAS present but verification still failed, state.reason
        # names exactly why (TOKEN_INVALID_SIGNATURE/JWK_KID_MISMATCH ->
        # CLERK_SECRET_KEY/CLERK_JWT_KEY don't match the instance that
        # issued the token; TOKEN_INVALID_AUTHORIZED_PARTIES ->
        # PUBLIC_BASE_URL/authorized_parties mismatch) -- added
        # 2026-08-11 to debug a real production case where the
        # client-side session was valid but this kept silently returning
        # None with no visible signal why.
        if "__session" in request.cookies:
            logger.warning(
                "Clerk session cookie present but verification failed: %s",
                getattr(state, "message", None) or getattr(state, "reason", None),
            )
        return None
    return state.payload.get("sub")
