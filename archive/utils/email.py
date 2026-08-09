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

import logging
import os

import aiohttp

logger = logging.getLogger("rtr_archive.email")

_TIMEOUT = aiohttp.ClientTimeout(total=10)


def _api_key() -> str:
    return os.environ.get("RESEND_API_KEY", "")


def _audience_id() -> str:
    return os.environ.get("RESEND_AUDIENCE_ID", "")


def _headers() -> dict:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


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
