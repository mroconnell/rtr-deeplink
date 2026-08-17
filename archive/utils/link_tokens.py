"""Signed, unauthenticated-clickable tokens for the per-search alert
unsubscribe link (see archive/search_alerts.py). The recipient isn't
logged in when clicking a link from their inbox, so the click itself
can't carry a clerk_user_id the way every other saved-item mutation in
this codebase (crud.unsave_item) already requires -- the token has to be
self-authorizing instead.

A dedicated `ALERT_UNSUBSCRIBE_SECRET` env var, not a reuse of
`CLERK_SECRET_KEY`/`ARCHIVE_INGEST_TOKEN` -- both of those are
auth/service-boundary secrets for a different security property, and
reusing one for unrelated HMAC signing is exactly the kind of coupling
that's cheap to avoid now and expensive to unwind later if either secret
ever needs independent rotation.
"""

import hashlib
import hmac
import os
from typing import Optional


def _secret() -> bytes:
    return os.environ.get("ALERT_UNSUBSCRIBE_SECRET", "").encode("utf-8")


def _signature(saved_item_id: int) -> str:
    return hmac.new(
        _secret(), str(saved_item_id).encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]


def sign_saved_item_id(saved_item_id: int) -> str:
    """Builds a token that embeds the id itself, not a separate
    tamperable query param -- `f"{id}.{signature}"`, so the id and its
    signature always travel together as one opaque string."""
    return f"{saved_item_id}.{_signature(saved_item_id)}"


def verify_saved_item_token(token: str) -> Optional[int]:
    """Returns the saved_item_id if `token` is genuine and untampered,
    else None. Fails closed on any malformed input (missing separator,
    non-integer id, wrong-length signature) rather than raising -- a
    clicked link is untrusted user input, same treatment as every other
    externally-supplied value this codebase parses defensively."""
    if not token or "." not in token:
        return None
    raw_id, _, signature = token.partition(".")
    try:
        saved_item_id = int(raw_id)
    except ValueError:
        return None
    if not _secret():
        return None
    expected = _signature(saved_item_id)
    if not hmac.compare_digest(expected, signature):
        return None
    return saved_item_id
