"""Auto-announce brand-new, high-quality Archive pages on social media
(Bluesky and/or Mastodon).

Fired from /internal/ingest (archive/main.py) via BackgroundTasks, only
when crud.ingest_resolution() reports it *created* the page -- a
re-ingest of an existing page (the resolver's push-retry sweep, the
corpus-wide backfill script, a stale-page recheck) can never trigger a
post, no matter how many times it runs. On top of that gate, the
SocialPost table (archive/db/models.py) dedups per (page, network) with
a claim-first insert, so even a race between two concurrent first
ingests produces at most one post per network.

"High quality" deliberately mirrors app/db/outcomes.py's "success"
bucket -- real video + real transcript, no garbled/hallucination
warning, English-or-undetected language -- plus a minimum segment count,
because a technically-successful 3-line caption file is not something
worth announcing publicly. See payload_is_high_quality().

Error handling is deliberately at-most-once, not at-least-once: a
claimed post that then fails at the network stays "failed" in the
SocialPost table and is never retried automatically. A missed
announcement is a shrug; a duplicate post on a public account is spam.

NOT YET LIVE-VERIFIED (2026-08-17): both clients are written against the
documented, stable public APIs (Bluesky's com.atproto XRPC endpoints,
Mastodon's /api/v1/statuses) but no real account/credentials existed at
build time, so neither has made a real post yet -- the same
"schema-verified but not content-verified" flag this repo uses for
unproven adapter fields (see CLAUDE.md). BACKLOG.md tracks the live
verification step.

Config (all optional -- unset network = that network silently disabled):
  BLUESKY_HANDLE / BLUESKY_APP_PASSWORD  e.g. rtr.bsky.social + an app
      password from Settings > App Passwords (never the account password)
  BLUESKY_SERVICE_URL                    default https://bsky.social
  MASTODON_BASE_URL / MASTODON_ACCESS_TOKEN  instance base URL + an
      access token (Preferences > Development > New application, scope
      write:statuses)
  SOCIAL_MIN_SEGMENTS                    default 50
  PUBLIC_BASE_URL                        required -- posts link to
      {PUBLIC_BASE_URL}/m/{slug}; nothing posts without it
"""

import logging
import os
from datetime import datetime, timezone

import aiohttp

from ..db import crud

logger = logging.getLogger("rtr_archive")

_TIMEOUT = aiohttp.ClientTimeout(total=20)

# Bluesky's post limit is 300 graphemes; Mastodon's default is 500
# characters (and it counts any URL as 23). A single composition capped
# at Bluesky's stricter limit is valid for both, so one compose_post()
# serves both networks rather than per-network variants.
_POST_CHAR_LIMIT = 300

_DEFAULT_MIN_SEGMENTS = 50


def enabled_networks() -> list[str]:
    """Read env at call time (same pattern as email.py/archive_client.py)
    so tests and a mid-session Render env edit both behave predictably."""
    networks = []
    if os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD"):
        networks.append("bluesky")
    if os.environ.get("MASTODON_BASE_URL") and os.environ.get("MASTODON_ACCESS_TOKEN"):
        networks.append("mastodon")
    return networks


def payload_is_high_quality(payload: dict) -> bool:
    """Mirror of app/db/outcomes.py's "success" classification, applied to
    the ingest payload (ResolvedMeeting.model_dump() shape) instead of a
    MeetingResolution row: video + transcript present, no garbled/
    hallucination warning (crud's markers, kept in sync with outcomes.py
    -- see the comment on crud._GARBLED_MARKER), and language either
    English or undetected (outcomes.py only flags a *detected* non-English
    language; an undetected one still counts as success there, so it does
    here too).

    The extra minimum-segment-count bar is this module's own, deliberately
    stricter than outcomes.py: announcing a page publicly warrants more
    than the bare "any non-empty transcript" that counts as a successful
    resolve. Real meetings run hundreds-to-thousands of segments;
    SOCIAL_MIN_SEGMENTS=50 keeps out caption stubs without excluding any
    plausible real meeting.
    """
    if not payload.get("video_url"):
        return False
    segments = payload.get("segments") or []
    min_segments = int(
        os.environ.get("SOCIAL_MIN_SEGMENTS", str(_DEFAULT_MIN_SEGMENTS))
    )
    if len(segments) < min_segments:
        return False
    if not crud._has_real_warning_free_transcript(payload.get("transcript_warnings")):
        return False
    language = payload.get("transcript_language")
    if language and language != "en":
        return False
    return True


# If truncating the title (with the footer kept) would leave less than
# this much of it, drop the footer first instead -- "Pla…" mid-sentence
# reads worse than losing the jurisdiction/date line.
_MIN_TRUNCATED_TITLE = 20


def compose_post(
    title, jurisdiction, date, url: str, limit: int = _POST_CHAR_LIMIT
) -> str:
    """One post text valid for every enabled network (<= 300 chars, the
    strictest limit -- see _POST_CHAR_LIMIT). Wording is Ryan's
    (2026-08-21). The sentence and the permalink always survive whole;
    when the total runs over the limit (the sentence's ~106 fixed chars +
    a full-length slug URL leave a real but finite title budget), the
    ladder is: truncate the title with an ellipsis, and if that would
    gut the title below _MIN_TRUNCATED_TITLE chars, drop the
    jurisdiction/date footer line instead and give the title the larger
    budget."""
    name = (title or "").strip() or "a public meeting"
    footer_parts = [p.strip() for p in (jurisdiction, date) if p and p.strip()]
    footer = "\n\n" + " — ".join(footer_parts) if footer_parts else ""

    def build(n: str, f: str) -> str:
        return (
            f"Somebody looked up {n} — you can now search a transcript of "
            f"that meeting and link to specific timestamps at {url}{f}"
        )

    text = build(name, footer)
    if len(text) <= limit:
        return text

    budget = limit - len(build("", footer)) - 1  # -1 for the ellipsis
    if budget < _MIN_TRUNCATED_TITLE:
        footer = ""
        budget = limit - len(build("", "")) - 1
    truncated = name[: max(budget, 1)].rstrip() + "…"
    return build(truncated, footer)


async def _post_to_bluesky(text: str, link_url: str) -> str:
    """Two XRPC calls: createSession with the app password, then
    createRecord for the post itself. The explicit link facet (byte
    offsets into the UTF-8 text) is what makes the URL clickable --
    Bluesky does no server-side autolinking. Returns the created
    record's at:// URI."""
    service = os.environ.get("BLUESKY_SERVICE_URL", "https://bsky.social").rstrip("/")
    handle = os.environ["BLUESKY_HANDLE"]
    app_password = os.environ["BLUESKY_APP_PASSWORD"]

    encoded = text.encode("utf-8")
    byte_start = encoded.rfind(link_url.encode("utf-8"))
    facets = []
    if byte_start >= 0:
        facets.append(
            {
                "index": {
                    "byteStart": byte_start,
                    "byteEnd": byte_start + len(link_url.encode("utf-8")),
                },
                "features": [
                    {"$type": "app.bsky.richtext.facet#link", "uri": link_url}
                ],
            }
        )

    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        async with session.post(
            f"{service}/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": app_password},
        ) as response:
            response.raise_for_status()
            auth = await response.json()

        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }
        if facets:
            record["facets"] = facets

        async with session.post(
            f"{service}/xrpc/com.atproto.repo.createRecord",
            json={
                "repo": auth["did"],
                "collection": "app.bsky.feed.post",
                "record": record,
            },
            headers={"Authorization": f"Bearer {auth['accessJwt']}"},
        ) as response:
            response.raise_for_status()
            created = await response.json()
    return created.get("uri", "")


async def _post_to_mastodon(text: str, idempotency_key: str) -> str:
    """Single statuses call; Mastodon autolinks URLs in the text, no
    facet equivalent needed. Idempotency-Key is a real, documented
    Mastodon feature -- a second layer of duplicate protection on top of
    the SocialPost claim, free to include. Returns the status URL."""
    base = os.environ["MASTODON_BASE_URL"].rstrip("/")
    token = os.environ["MASTODON_ACCESS_TOKEN"]

    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        async with session.post(
            f"{base}/api/v1/statuses",
            json={"status": text, "visibility": "public"},
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": idempotency_key,
            },
        ) as response:
            response.raise_for_status()
            status = await response.json()
    return status.get("url", "")


async def announce_new_page(page_id: int, slug: str, payload: dict) -> None:
    """The BackgroundTasks entry point -- called only for a freshly
    *created* page (see /internal/ingest in archive/main.py). Applies the
    quality gate, then claims + posts per enabled network. Never raises:
    a social failure must not surface anywhere near the ingest path.
    """
    try:
        networks = enabled_networks()
        if not networks:
            return
        base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
        if not base_url:
            # Without the real public domain there's no meaningful link to
            # post -- and a relative or onrender.com URL on a public feed
            # would be worse than no post.
            logger.warning(
                "Social posting enabled but PUBLIC_BASE_URL unset; skipping."
            )
            return
        if not payload_is_high_quality(payload):
            return

        page_url = f"{base_url}/m/{slug}"
        text = compose_post(
            payload.get("title"),
            payload.get("jurisdiction"),
            payload.get("date"),
            page_url,
        )

        for network in networks:
            claim_id = await crud.claim_social_post(page_id, network)
            if claim_id is None:
                continue  # already claimed/posted by a concurrent ingest
            try:
                if network == "bluesky":
                    post_uri = await _post_to_bluesky(text, page_url)
                else:
                    post_uri = await _post_to_mastodon(text, f"rtr-page-{page_id}")
                await crud.finish_social_post(
                    claim_id, status="posted", post_uri=post_uri
                )
                logger.info("Announced /m/%s on %s: %s", slug, network, post_uri)
            except Exception as e:
                await crud.finish_social_post(claim_id, status="failed", error=str(e))
                logger.exception("Social post to %s failed for /m/%s", network, slug)
    except Exception:
        logger.exception("announce_new_page failed for /m/%s", slug)
