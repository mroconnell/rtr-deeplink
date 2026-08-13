"""Saved-search alert sweep: for every saved_search SavedItem, finds
meetings archived since it was last checked, groups new matches by
account, and sends one digest email per account (never one email per
match -- Resend has no built-in batching, so the accumulation happens
here). Called by GET /admin/send-search-alerts (app/main.py) via
app/archive_client.py -> POST /internal/account/send-search-alerts
(archive/main.py), and by scripts/send_search_alerts.py's CLI wrapper --
mirrors app/reporting.py's "gather -> compose -> send -> dry-run-able
dict" shape, the same pattern the existing daily-report digest uses.

The user's email address is fetched live from Clerk's Backend API at
send time, never stored -- SavedItem holds zero PII by design (see its
own docstring in archive/db/models.py), and there's no earlier point in
this feature's flow (unlike a form submission) where an email address
would naturally be captured and stored.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from .db import crud
from .utils import email as email_utils
from .utils import link_tokens
from .utils.search import find_matching_segment

logger = logging.getLogger("rtr_archive.search_alerts")


async def get_user_contact(clerk_user_id: str) -> Optional[dict]:
    """Live Clerk Backend API lookup -- {"email": str, "first_name":
    Optional[str]} or None. Fails closed on any error, missing
    CLERK_SECRET_KEY, or a user with no primary email -- a recipient we
    can't safely resolve is logged and skipped, not a reason to crash
    the whole sweep (same "one bad item doesn't blank out the rest"
    instinct as app/reporting.py's MetricResult)."""
    secret_key = os.environ.get("CLERK_SECRET_KEY", "")
    if not secret_key:
        return None

    from clerk_backend_api import Clerk

    try:
        async with Clerk(bearer_auth=secret_key) as clerk:
            user = await clerk.users.get_async(user_id=clerk_user_id)
    except Exception:
        logger.exception("Clerk user lookup failed for a saved-search alert recipient.")
        return None

    email_address = next(
        (e.email_address for e in (user.email_addresses or []) if e.id == user.primary_email_address_id),
        None,
    )
    if not email_address:
        return None
    return {"email": email_address, "first_name": user.first_name}


def _build_page_url(base_url: str, slug: str, segment: Optional[dict], version_id: Optional[int]) -> str:
    url = f"{base_url}/m/{slug}"
    if not segment or segment.get("start") is None:
        return url
    params = [f"t={int(segment['start'])}", f"line=seg-{segment['index']}"]
    if version_id is not None:
        params.append(f"version={version_id}")
    return f"{url}?{'&'.join(params)}"


async def _matches_for_saved_search(item: dict, *, base_url: str) -> list[dict]:
    """Runs one saved search's stored query, and for each new match
    resolves the real matching transcript segment (for a proper quote +
    a deep link to that exact moment) when there's a keyword to look for
    at all -- a keyword-less filter search has nothing to locate a
    segment for, same as find_matching_segment()'s own None case."""
    keyword = item["search_params"].get("q")
    fuzzy = bool(item["search_params"].get("fuzzy", False))
    pages = await crud.find_new_matches_for_saved_search(item["search_params"], since=item["last_alerted_at"])

    matches = []
    for page in pages:
        segment = None
        version_id = None
        if keyword:
            full_page = await crud.get_page_by_slug(page["slug"])
            if full_page:
                default_version = next((v for v in full_page["versions"] if v["is_default"]), None)
                if default_version:
                    version_id = default_version["id"]
                    segment = find_matching_segment(keyword, default_version["segments"] or [], fuzzy)
        matches.append(
            {
                "title": page["title"],
                "date": page["date"],
                "jurisdiction": page["jurisdiction"],
                "page_url": _build_page_url(base_url, page["slug"], segment, version_id),
                "quote_html": segment["quote_html"] if segment else None,
            }
        )
    return matches


async def run_search_alerts(*, dry_run: bool = False) -> dict:
    """Entry point. Returns a summary dict either way (dry_run or real):
    {"saved_searches_checked", "users_emailed", "matches_found", "sent":
    [{"clerk_user_id", "email", "subject"}]}.

    Only advances last_alerted_at for saved searches that contributed to
    a digest that actually sent -- a failed Resend send, a missing
    email, or dry_run must never silently move the cursor forward and
    lose that match. Groups every user's new matches across *all* their
    saved searches into one accumulation pass before any send happens,
    so one email per user is a natural consequence of the loop order,
    not a separate dedup step.
    """
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    checked_at = datetime.now(timezone.utc)

    saved_searches = await crud.list_all_saved_searches()
    by_user: dict[str, list[dict]] = {}
    for item in saved_searches:
        matches = await _matches_for_saved_search(item, base_url=base_url)
        if not matches:
            continue
        by_user.setdefault(item["clerk_user_id"], []).append(
            {"saved_item_id": item["id"], "keyword": item["search_params"].get("q"), "matches": matches}
        )

    sent: list[dict] = []
    matches_found = sum(len(g["matches"]) for groups in by_user.values() for g in groups)

    for clerk_user_id, groups in by_user.items():
        contact = await get_user_contact(clerk_user_id)
        if not contact:
            logger.warning("Skipping saved-search alert for %s -- no resolvable email.", clerk_user_id)
            continue

        email_groups = [
            {
                "keyword": g["keyword"],
                "unsubscribe_url": f"{base_url}/alerts/unsubscribe?token={link_tokens.sign_saved_item_id(g['saved_item_id'])}",
                "matches": g["matches"],
            }
            for g in groups
        ]

        # Composed once, up front -- used for the dry-run summary as-is,
        # or handed straight to email_utils._send() below on a real run
        # so this never recomposes (and never risks the two paths
        # producing subtly different output).
        subject, body = email_utils.compose_search_alert_digest(first_name=contact["first_name"], groups=email_groups)

        if dry_run:
            sent.append({"clerk_user_id": clerk_user_id, "email": contact["email"], "subject": subject, "body": body})
            continue

        ok = await email_utils._send(contact["email"], subject, body)
        if not ok:
            logger.error("Search-alert digest send failed for %s -- cursor left unadvanced.", clerk_user_id)
            continue

        saved_item_ids = [g["saved_item_id"] for g in groups]
        await crud.mark_saved_searches_alerted(saved_item_ids, checked_at)
        sent.append({"clerk_user_id": clerk_user_id, "email": contact["email"], "subject": subject, "body": body})

    return {
        "saved_searches_checked": len(saved_searches),
        "users_emailed": len(sent),
        "matches_found": matches_found,
        "sent": sent,
    }
