"""Resend integration for the Archive service -- transactional sends
(confirmation + transcription-complete emails) plus an audience-membership
check, neither of which existed anywhere in this codebase before. The
resolver's `/api/newsletter/signup` (app/main.py) only ever POSTs a contact
into the audience; it never reads one back or sends a one-off email.

**Needs live verification against a real Resend account before trusting
in production** -- the contact-lookup-by-email endpoint shape below is
Resend's documented REST convention, not yet confirmed live the way this
repo's other integrations are (see CLAUDE.md's "don't claim a path works
without a positive example" convention). `RESEND_API_KEY` needs "Full
access" scope (same requirement already documented in .env.example for
the audiences endpoint), and per render.yaml, this key currently only
exists in the resolver's service env -- the Archive service needs its own
copy added too (see the render.yaml task this was built alongside).
"""

import html
import logging
import os
from urllib.parse import quote

import aiohttp

logger = logging.getLogger("rtr_archive.email")

_TIMEOUT = aiohttp.ClientTimeout(total=10)


def _api_key() -> str:
    return os.environ.get("RESEND_API_KEY", "")


def _audience_id() -> str:
    return os.environ.get("RESEND_AUDIENCE_ID", "")


def _headers() -> dict:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


def _unsubscribe_footer_html(to: str) -> str:
    """Real, working one-click unsubscribe link on every email this module
    sends -- per Resend's own deliverability guidance (a missing opt-out
    path hurts sender reputation across *all* sends from a domain, not
    just "true" marketing ones), added 2026-08-10 alongside switching
    RESEND_FROM_ADDRESS off a noreply@ address for the same reason (see
    that guidance's own "don't use noreply" section). Points at a new
    GET /unsubscribe route on the *resolver* (app/main.py, not this
    service) -- matches /confirm-transcription's existing precedent of
    living there rather than here, since the resolver owns the public
    domain this link needs to work from a plain email click, and already
    has its own direct Resend credentials (see /api/newsletter/signup).
    No login, no confirmation step, matching CAN-SPAM's one-click
    requirement. Returns "" (no footer at all) when
    PUBLIC_BASE_URL isn't set -- local dev has no real public URL to
    build a working link from.
    """
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        return ""
    unsubscribe_url = f"{base}/unsubscribe?email={quote(to)}"
    return (
        f'<p style="margin-top:24px;font-size:12px;color:#999;">'
        f'<a href="{unsubscribe_url}" style="color:#999;">Unsubscribe</a> from future emails.</p>'
    )


async def is_configured() -> bool:
    return bool(_api_key())


async def check_audience_membership(email: str) -> bool:
    """True if this email is already an active contact in the newsletter
    audience -- used to decide whether a transcription request can skip
    the confirm-by-email step (see archive/db/crud.py's
    create_transcription_job `skip_confirmation` param). Fails closed
    (returns False, i.e. "require confirmation") on any error, including
    Resend being unconfigured -- a false negative here just costs someone
    one extra confirmation click, which is far safer than a false
    positive silently skipping the anti-abuse gate this exists for.
    """
    api_key, audience_id = _api_key(), _audience_id()
    if not api_key or not audience_id:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.resend.com/audiences/{audience_id}/contacts/{email}",
                headers=_headers(),
                timeout=_TIMEOUT,
            ) as response:
                if response.status != 200:
                    return False
                data = await response.json()
                return not data.get("unsubscribed", False)
    except Exception:
        logger.exception("Resend audience-membership check failed for an email address.")
        return False


async def upsert_audience_contact(email: str) -> bool:
    """Adds/reactivates a contact in the newsletter audience -- called
    after a first-time transcription requester confirms their email, so
    every request after their first is frictionless (same "confirm once,
    frictionless forever" behavior /api/newsletter/signup already gives
    newsletter subscribers). Mirrors that endpoint's exact POST shape.
    """
    api_key, audience_id = _api_key(), _audience_id()
    if not api_key or not audience_id:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.resend.com/audiences/{audience_id}/contacts",
                headers=_headers(),
                json={"email": email, "unsubscribed": False},
                timeout=_TIMEOUT,
            ) as response:
                return response.status < 300
    except Exception:
        logger.exception("Resend audience upsert failed for an email address.")
        return False


async def _send(to: str, subject: str, html: str) -> bool:
    api_key = _api_key()
    from_address = os.environ.get("RESEND_FROM_ADDRESS", "")
    if not api_key or not from_address:
        logger.error("Transactional email send attempted but RESEND_API_KEY/RESEND_FROM_ADDRESS isn't configured.")
        return False

    # Appended centrally, once, here -- rather than at each of the four
    # send_*() call sites below -- so "every email this module sends gets
    # a real unsubscribe link" is guaranteed structurally, not dependent
    # on remembering to add it correctly at each new email built later.
    html = html + _unsubscribe_footer_html(to)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.resend.com/emails",
                headers=_headers(),
                json={"from": from_address, "to": [to], "subject": subject, "html": html},
                timeout=_TIMEOUT,
            ) as response:
                if response.status < 300:
                    return True
                logger.error("Resend transactional send failed (%s): %s", response.status, await response.text())
                return False
    except Exception:
        logger.exception("Resend transactional send request failed.")
        return False


async def send_confirmation_email(to: str, confirm_url: str) -> bool:
    html = (
        "<p>Someone (hopefully you) asked Red Tape Recordings to transcribe a public "
        "meeting from its audio, and used this email address for the first time.</p>"
        f'<p><a href="{confirm_url}">Confirm this request</a> to start the transcription.</p>'
        "<p>If you didn't request this, you can ignore this email.</p>"
    )
    return await _send(to, "Confirm your transcription request", html)


async def send_completion_email(to: str, *, meeting_title: str, excerpt: str, page_url: str) -> bool:
    # Every completion email is, by definition, about an AI-transcribed
    # version -- this function only ever gets called from the
    # transcription-job completion path -- so the disclaimer applies
    # unconditionally, no source check needed (unlike the on-page/export
    # versions, which can also show a real scraped caption). Same wording
    # as the on-page disclaimer (archive/templates/meeting_page.html) --
    # keep them matching if either ever changes.
    #
    # "Brand-lite" per the decided scope in BACKLOG.md: no logo asset
    # exists in this repo yet, and building one is its own task -- so
    # this hand-inlines the site's real colors/font (--primary navy
    # #2c3e50, --accent blue #3498db, the amber warning-pill pair
    # #ffe6a1/#a84b00, Georgia serif) as literal hex/font-family values
    # on each tag, since most email clients strip <style> blocks and CSS
    # variables outright -- a different, uglier discipline than the rest
    # of this codebase's CSS, but the only one that reliably renders.
    # A single outer table (not just divs) for the page background,
    # since Outlook desktop's Word rendering engine handles table-based
    # layouts far more predictably than div/CSS ones.
    html = f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fa;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border:1px solid #ddd;">
<tr><td style="background:#b71c1c;padding:14px 24px;">
<span style="font-family:'Courier New',monospace;font-weight:bold;letter-spacing:0.11em;font-size:15px;color:#ffffff;border:2px solid #a84b00;padding:4px 14px;display:inline-block;">RED TAPE RECORDINGS</span>
</td></tr>
<tr><td style="padding:28px 24px 8px;">
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:17px;color:#2c3e50;">Your requested transcript for <strong>{meeting_title}</strong> is ready.</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="background:#ffe6a1;border-radius:6px;margin:0 0 20px;">
<tr><td style="padding:12px 16px;font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#a84b00;">
<strong>AI transcript:</strong> generated automatically from audio and hasn't been reviewed by a person &mdash; it can contain mistakes, including plausible-sounding sentences that were never actually said. Treat it as a starting point, not a verbatim record.
</td></tr>
</table>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 20px;">
<tr><td style="border-left:3px solid #ddd;padding:2px 0 2px 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;font-style:italic;color:#666;">
{excerpt}&hellip;
</td></tr>
</table>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
<tr><td style="background:#ffffff;border:2px solid #222;">
<a href="{page_url}" style="display:inline-block;padding:10px 22px;font-family:'Courier New',monospace;font-weight:bold;font-size:15px;letter-spacing:0.5px;color:#222426;text-decoration:none;">Read the full transcript &rarr;</a>
</td></tr>
</table>
<p style="margin:0 0 24px;font-family:Georgia,'Times New Roman',serif;font-size:13px;color:#666;">Know someone else who'd find this useful? Forward this email, or share the link directly: <a href="{page_url}" style="color:#3498db;">{page_url}</a></p>
</td></tr>
</table>
</td></tr>
</table>
"""
    return await _send(to, f'Transcript ready: "{meeting_title}"', html)


async def send_youtube_transcript_report(to: str, *, ingested: list, skipped: list, failed: list) -> bool:
    """Daily report for scripts/fetch_youtube_transcripts.py's launchd
    run -- every meeting a transcript was actually added to, plus a
    quick summary of anything skipped or failed along the way. Sent on
    every normal completion, even an empty one, so silence itself
    becomes a signal something's wrong (the launchd job not firing at
    all) rather than being indistinguishable from "nothing new today."

    An internal ops notification, not a public-facing email -- plain
    HTML, not the branded template send_completion_email() above uses.
    Titles/slugs/error details are escaped since they ultimately trace
    back to scraped government page content, not hand-typed text.
    """
    if ingested:
        rows = "".join(
            f'<li><a href="{html.escape(item["page_url"])}">{html.escape(item["title"])}</a>'
            f" &mdash; {item['segment_count']} segments</li>"
            for item in ingested
        )
        body = f"<p><strong>{len(ingested)} transcript(s) added:</strong></p><ul>{rows}</ul>"
    else:
        body = "<p>No new transcripts today.</p>"

    if failed:
        rows = "".join(f"<li>{html.escape(item['slug'])}: {html.escape(item['detail'])}</li>" for item in failed)
        body += f"<p><strong>{len(failed)} failed:</strong></p><ul>{rows}</ul>"
    if skipped:
        rows = "".join(f"<li>{html.escape(item['slug'])}: {html.escape(item['detail'])}</li>" for item in skipped)
        body += f"<p>{len(skipped)} skipped:</p><ul>{rows}</ul>"

    subject = f"YouTube transcripts: {len(ingested)} added" if ingested else "YouTube transcripts: none new today"
    return await _send(to, subject, body)


async def send_youtube_transcript_failure(to: str, *, error_message: str) -> bool:
    """The "different alert" for when the daily fetch didn't just find
    zero/some failed videos but failed to complete a normal run at all
    (an IP-level block aborting mid-run, or an unhandled exception) --
    deliberately a different subject/shape from the report above so it
    reads as urgent rather than routine.
    """
    body = (
        "<p>The daily YouTube transcript fetch failed to complete.</p>"
        f"<p><strong>Error:</strong> {html.escape(error_message)}</p>"
        "<p>Check <code>~/Library/Logs/fetch-youtube-transcripts.log</code> on the machine "
        "running the launchd job for the full detail.</p>"
    )
    return await _send(to, "⚠️ YouTube transcript fetch failed", body)
