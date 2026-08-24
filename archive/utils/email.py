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
from typing import Optional
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
        logger.exception(
            "Resend audience-membership check failed for an email address."
        )
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


async def _send(to: str, subject: str, html: str, *, cc: str = "") -> bool:
    api_key = _api_key()
    from_address = os.environ.get("RESEND_FROM_ADDRESS", "")
    if not api_key or not from_address:
        logger.error(
            "Transactional email send attempted but RESEND_API_KEY/RESEND_FROM_ADDRESS isn't configured."
        )
        return False

    # Appended centrally, once, here -- rather than at each of the four
    # send_*() call sites below -- so "every email this module sends gets
    # a real unsubscribe link" is guaranteed structurally, not dependent
    # on remembering to add it correctly at each new email built later.
    html = html + _unsubscribe_footer_html(to)

    payload = {"from": from_address, "to": [to], "subject": subject, "html": html}
    if cc:
        payload["cc"] = [cc]
    # RESEND_FROM_ADDRESS lives on ally.redtaperecordings.com, a subdomain
    # dedicated to Resend's own sending DNS (SPF/DKIM/bounce MX) -- it has
    # no real inbox behind it. reply_to points replies at the root domain
    # instead, which Namecheap's free forwarding *can* manage cleanly
    # (unlike the ally subdomain, whose existing Resend MX record blocks
    # Namecheap's forwarding wizard -- see BACKLOG_DONE.md).
    reply_to = os.environ.get("RESEND_REPLY_TO_ADDRESS", "")
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.resend.com/emails",
                headers=_headers(),
                json=payload,
                timeout=_TIMEOUT,
            ) as response:
                if response.status < 300:
                    return True
                logger.error(
                    "Resend transactional send failed (%s): %s",
                    response.status,
                    await response.text(),
                )
                return False
    except Exception:
        logger.exception("Resend transactional send request failed.")
        return False


def _branded_wrapper(body_html: str, base_url: str = "") -> str:
    """Shared branded skeleton (RTR header bar + white content card) behind
    every warmer, first-person-from-Ryan email this module sends -- see
    rtr-business's marketing/LIFECYCLE_EMAILS.md for the approved copy/
    voice these build on. "Brand-lite" per the decided scope in
    BACKLOG.md: no logo asset exists in this repo yet, and building one is
    its own task -- so this hand-inlines the site's real colors/font
    (--primary navy #2c3e50, --accent blue #3498db, the amber warning-pill
    pair #ffe6a1/#a84b00, Georgia serif) as literal hex/font-family values
    on each tag, since most email clients strip <style> blocks and CSS
    variables outright -- a different, uglier discipline than the rest of
    this codebase's CSS, but the only one that reliably renders. A single
    outer table (not just divs) for the page background, since Outlook
    desktop's Word rendering engine handles table-based layouts far more
    predictably than div/CSS ones.

    Real bug fixed 2026-08-11: this used to have the outer cell itself in
    the label's own red (#b71c1c) with the inner span unstyled (just a
    border) -- the reverse of the real on-site .dymo-label look, where a
    red label sits *inside* a separately-dark navbar (bg-dark) and reads
    as a label specifically because of that contrast. Outer cell is now a
    dark shade matching bg-dark, with the inner span carrying its own
    explicit red background -- and the text is real Title Case ("Red Tape
    Recordings", matching base.html's actual markup) instead of hardcoded
    ALL CAPS. base_url (when set) also makes the wordmark a real link back
    to the site, matching _signoff_html()'s sign-off line below.
    """
    wordmark = "Red Tape Recordings"
    if base_url:
        wordmark = f'<a href="{base_url}" style="color:#ffffff;text-decoration:none;">{wordmark}</a>'
    return f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fa;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border:1px solid #ddd;">
<tr><td style="background:#212529;padding:14px 24px;">
<span style="background:#b71c1c;font-family:'Courier New',monospace;font-weight:bold;letter-spacing:0.11em;font-size:15px;color:#ffffff;border:2px solid #a84b00;padding:4px 14px;display:inline-block;">{wordmark}</span>
</td></tr>
<tr><td style="padding:28px 24px 8px;">
{body_html}
</td></tr>
</table>
</td></tr>
</table>
"""


def _signoff_html(base_url: str = "") -> str:
    # Matches the house-style sign-off in marketing/LIFECYCLE_EMAILS.md,
    # used on every lifecycle email built from that doc. base_url (when
    # set) links "Red Tape Recordings" back to the site -- real bug fixed
    # 2026-08-11, this was plain unlinked text before.
    name = "Red Tape Recordings"
    if base_url:
        name = f'<a href="{base_url}" style="color:#2c3e50;">{name}</a>'
    return (
        "<p style=\"margin:24px 0 0;font-family:Georgia,'Times New Roman',serif;"
        f'font-size:14px;color:#2c3e50;">Signing out,<br>Ryan<br>{name}</p>'
    )


async def send_confirmation_email(to: str, confirm_url: str) -> bool:
    body_html = (
        "<p>Someone (hopefully you) asked Red Tape Recordings to transcribe a public "
        "meeting from its audio, and used this email address for the first time.</p>"
        f'<p><a href="{confirm_url}">Confirm this request</a> to start the transcription.</p>'
        "<p>If you didn't request this, you can ignore this email.</p>"
    )
    return await _send(to, "Confirm your transcription request", body_html)


async def send_completion_email(
    to: str,
    *,
    meeting_title: str,
    excerpt: str,
    page_url: str,
    first_name: Optional[str] = None,
) -> bool:
    # "Your pizza is ready" per marketing/LIFECYCLE_EMAILS.md #4. Every
    # completion email is, by definition, about an AI-transcribed version
    # -- this function only ever gets called from the transcription-job
    # completion path -- so the disclaimer box below applies
    # unconditionally, no source check needed (unlike the on-page/export
    # versions, which can also show a real scraped caption). Same wording
    # as the on-page disclaimer (archive/templates/meeting_page.html) --
    # keep them matching if either ever changes. Kept deliberately even
    # though the approved copy doc doesn't mention it -- a real standing
    # accuracy-expectation warning, not just legal cover.
    #
    # No first_name is ever actually available yet: nothing in the
    # transcription-request flow (confirm-by-email only) collects a name.
    # "Hi there," is the documented fallback for exactly this case.
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    greeting_name = html.escape(first_name) if first_name else "there"
    title = html.escape(meeting_title)
    body_html = f"""\
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:17px;color:#2c3e50;">Hi {greeting_name},</p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">Your transcript for <strong>{title}</strong> is ready whenever you are.</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 20px;">
<tr><td style="background:#ffffff;border:2px solid #222;">
<a href="{page_url}" style="display:inline-block;padding:10px 22px;font-family:'Courier New',monospace;font-weight:bold;font-size:15px;letter-spacing:0.5px;color:#222426;text-decoration:none;">Open it up &rarr;</a>
</td></tr>
</table>
<table role="presentation" cellpadding="0" cellspacing="0" style="background:#ffe6a1;border-radius:6px;margin:0 0 20px;">
<tr><td style="padding:12px 16px;font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#a84b00;">
<strong>AI transcript:</strong> generated automatically from audio and hasn't been reviewed by a person, and it can contain mistakes, including plausible-sounding sentences that were never actually said. Treat it as a starting point, not a verbatim record.
</td></tr>
</table>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 20px;">
<tr><td style="border-left:3px solid #ddd;padding:2px 0 2px 16px;font-family:Georgia,'Times New Roman',serif;font-size:15px;font-style:italic;color:#666;">
{html.escape(excerpt)}&hellip;
</td></tr>
</table>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#2c3e50;">Click any line to jump to that moment in the video. When you find the part that matters, copy the "deep link," and it should take whoever you send it to right to that second.</p>
<p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#2c3e50;">Thanks for using Red Tape Recordings.</p>
"""
    body_html += _signoff_html(base_url)
    return await _send(
        to, "Your transcript's ready", _branded_wrapper(body_html, base_url)
    )


async def send_transcription_failed_email(
    to: str,
    *,
    meeting_title: str,
    page_url: str,
    first_name: Optional[str] = None,
    partial_coverage: Optional[str] = None,
) -> bool:
    """ "We couldn't cook this one" -- the sad-path twin to
    send_completion_email() above, per marketing/LIFECYCLE_EMAILS.md's
    "Bonus" entry ("A failure with no email just reads as broken"). CC's
    RESEND_REPLY_TO_ADDRESS (Ryan's real inbox, same address every other
    send in this module already routes replies to) so failures get seen
    and can be followed up on personally, matching the doc's own note.

    `partial_coverage` (e.g. "3 hours 12 minutes") turns this into a very
    different email, and it is the one that made the whole partial-
    publishing change worth building (2026-08-24): someone who asked for
    a transcript, waited, and is sitting on eighteen of twenty finished
    chunks should be told what they *got*, with a link to read it -- not
    that we failed. Subject line changes too, because "we hit a snag"
    over-reports a mostly-successful run. None keeps the original
    couldn't-do-it copy verbatim.
    """
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    greeting_name = html.escape(first_name) if first_name else "there"
    title = html.escape(meeting_title)
    p_lead = (
        "margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;"
        "font-size:15px;color:#2c3e50;"
    )
    body_html = f"""\
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:17px;color:#2c3e50;">Hi {greeting_name},</p>
"""
    if partial_coverage:
        coverage = html.escape(partial_coverage)
        subject = "Part of your transcript is ready"
        body_html += f"""\
<p style="{p_lead}">We got partway through <strong>{title}</strong> before the transcription was interrupted \u2014 but the part we finished is real, and it is on the page now.</p>
<p style="{p_lead}"><a href="{page_url}" style="color:#3498db;">Read the first {coverage} of the meeting</a>, every line clickable and linkable, same as any other transcript here.</p>
<p style="{p_lead}">We will try to finish the rest automatically. If it still looks short in a few days, reply to this email and we will chase it down.</p>
<p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#2c3e50;">Thank you for your patience, and for helping keep the record open.</p>
"""
    else:
        subject = "We hit a snag on your transcript"
        body_html += f"""\
<p style="{p_lead}">We tried to pull a transcript for <strong>{title}</strong> and couldn't get it done this time. Usually that means the video URL moved, the stream came down, or the file was in a format we couldn't read yet.</p>
<p style="{p_lead}">A couple of things worth trying: <a href="{page_url}" style="color:#3498db;">check that the link still plays</a>, or reply to this email with the page you found it on and we'll take a look.</p>
<p style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#2c3e50;">Sorry it wasn't ready. Thank you for your patience, and for helping keep the record open.</p>
"""
    body_html += _signoff_html(base_url)
    cc = os.environ.get("RESEND_REPLY_TO_ADDRESS", "")
    return await _send(
        to,
        subject,
        _branded_wrapper(body_html, base_url),
        cc=cc,
    )


async def send_admin_job_failure_alert(
    *,
    job_id: int,
    requester_email: str,
    meeting_title: str,
    page_url: str,
    source_url: Optional[str],
    chunks_completed: Optional[int],
    total_chunks: Optional[int],
    retry_count: int,
    error_message: Optional[str],
    failure_history: list,
    created_at: Optional[str],
) -> bool:
    """Operator-facing alert for a TranscriptionJob that gave up for good,
    separate from send_transcription_failed_email()'s branded "sorry, try
    again" copy above -- that email tells the requester nothing actionable
    happened wrong, on purpose, but that also means it carries none of the
    real diagnostics (which chunk, which error, how many retries) an
    operator actually needs to follow up. Real gap flagged 2026-08-19: job
    256 (a Redwood City, CA meeting, requested by a real early user) failed
    silently -- worker/main.py's failure-email call site turned out to be
    unreachable dead code (see that module's own note), so *neither* email
    had ever actually gone out for a real chunk-processing failure. Sent
    to TRANSCRIPTION_FAILURE_ALERT_EMAIL (default ryan@how-to-adu.com,
    same "leave unset to default" convention as DAILY_REPORT_EMAIL_TO --
    see .env.example) rather than reusing RESEND_REPLY_TO_ADDRESS, which
    is a CC on the requester's own branded email and not meant to carry a
    plain diagnostic dump.

    Plain, scannable HTML (a <pre> block) rather than the marketing-styled
    wrapper the requester-facing emails use -- this is read by one person
    debugging a real failure, not a visitor.
    """
    to = os.environ.get("TRANSCRIPTION_FAILURE_ALERT_EMAIL", "ryan@how-to-adu.com")
    recent_failures = (
        "\n".join(
            f"  chunk {entry.get('chunk_index')}: {entry.get('error')}  ({entry.get('at')})"
            for entry in failure_history[-10:]
        )
        or "  (no per-chunk history recorded)"
    )
    report = f"""\
job_id:            {job_id}
status:            failed (gave up after {retry_count} retr{"y" if retry_count == 1 else "ies"})
requester:         {requester_email}
meeting:           {meeting_title}
page:              {page_url}
source_url:        {source_url or "(unknown)"}
chunks_completed:  {chunks_completed} / {total_chunks}
created_at:        {created_at or "(unknown)"}
last error:        {error_message or "(none recorded)"}

recent chunk failures:
{recent_failures}
"""
    body_html = (
        '<pre style="font-family:ui-monospace,Menlo,Consolas,monospace;'
        'font-size:13px;color:#2c3e50;white-space:pre-wrap;">'
        f"{html.escape(report)}</pre>"
    )
    return await _send(
        to, f"Transcription job {job_id} failed: {meeting_title}", body_html
    )


def _digest_subject(groups: list) -> str:
    """Draft copy, not yet approved in marketing/LIFECYCLE_EMAILS.md --
    that doc's subject ('Somebody said "[keyword]"') was written for
    exactly one match; a digest can bundle several across multiple saved
    searches, including keyword-less filter searches with no "[keyword]"
    to quote at all. Shipped now per an explicit decision (easy to swap
    the literal strings once real copy is approved) rather than blocking
    the feature on a separate copy-approval pass.
    """
    total_matches = sum(len(g["matches"]) for g in groups)
    keywords = [g["keyword"] for g in groups if g.get("keyword")]
    if keywords:
        subject = f'Somebody said "{keywords[0]}"'
        extra = total_matches - 1
        return f"{subject} (+{extra} more)" if extra > 0 else subject
    plural = total_matches != 1
    return f"{total_matches} new meeting{'s' if plural else ''} {'match' if plural else 'matches'} your saved searches"


def compose_search_alert_digest(*, first_name: Optional[str], groups: list) -> tuple:
    """Builds (subject, html) for the saved-search alert digest, with no
    I/O -- separated from send_search_alert_digest() below so a dry run
    (archive/search_alerts.py's run_search_alerts(dry_run=True)) can
    compose and inspect real output without ever calling Resend, same
    "compose is pure, send is a thin wrapper" split app/reporting.py's
    compose_report_email()/send_report_email() already established for
    the daily report.

    "People are talking about..." per marketing/LIFECYCLE_EMAILS.md #5,
    adapted into a digest -- one email per user bundling every new match
    across *all* their saved searches, not one email per match (explicit
    decision; Resend has no built-in batching, so this app does the
    accumulation itself in archive/search_alerts.py before this is ever
    called).

    `groups` shape: `[{"keyword": Optional[str], "unsubscribe_url": str,
    "matches": [{"title": str, "date": Optional[str], "jurisdiction":
    Optional[str], "page_url": str, "quote_html": Optional[str]}]}]` --
    one entry per saved search that had at least one new match.
    `quote_html` is None when the match came from title/agenda text
    rather than any transcript segment (see
    archive/utils/search.py's find_matching_segment()) -- rendered as a
    plain title/date/link line with no quote in that case, since the
    approved copy's per-match quote can't exist for that entry.

    Each group gets its own "unsubscribe from this alert" link (deletes
    just that one saved search) *in addition to* the sitewide unsubscribe
    `_send()` already appends to every email -- the approved copy's
    "[unsubscribe from this alert]" is a second, more specific link, not
    a replacement.
    """
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    greeting_name = html.escape(first_name) if first_name else "there"

    sections = []
    for group in groups:
        match_rows = []
        for match in group["matches"]:
            title = html.escape(match["title"] or "Untitled meeting")
            meta = " &middot; ".join(
                html.escape(part)
                for part in (match.get("jurisdiction"), match.get("date"))
                if part
            )
            quote_block = (
                f'<td style="border-left:3px solid #ddd;padding:2px 0 2px 16px;'
                f"font-family:Georgia,'Times New Roman',serif;font-size:14px;font-style:italic;color:#666;\">"
                f"&hellip;{match['quote_html']}&hellip;</td>"
                if match.get("quote_html")
                else ""
            )
            match_rows.append(f"""\
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 14px;width:100%;">
<tr><td style="font-family:Georgia,'Times New Roman',serif;font-size:15px;color:#2c3e50;">
<strong>{title}</strong>{f'<br><span style="font-size:13px;color:#666;">{meta}</span>' if meta else ""}
</td></tr>
{f"<tr>{quote_block}</tr>" if quote_block else ""}
<tr><td style="padding-top:4px;"><a href="{match["page_url"]}" style="color:#3498db;font-family:Georgia,'Times New Roman',serif;font-size:14px;">Hear it in context &rarr;</a></td></tr>
</table>""")

        keyword_label = (
            f'"{html.escape(group["keyword"])}"'
            if group.get("keyword")
            else "your saved search"
        )
        sections.append(f"""\
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 20px;width:100%;border-top:1px solid #eee;padding-top:16px;">
<tr><td style="font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#666;padding-bottom:10px;">You asked us to watch for {keyword_label}, and it just came up:</td></tr>
<tr><td>{"".join(match_rows)}</td></tr>
<tr><td style="font-family:Georgia,'Times New Roman',serif;font-size:12px;color:#999;padding-top:4px;">
<a href="{group["unsubscribe_url"]}" style="color:#999;">Unsubscribe from this alert</a>
</td></tr>
</table>""")

    manage_url = f"{base_url}/account/saved" if base_url else "/account/saved"
    body_html = f"""\
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:17px;color:#2c3e50;">Hi {greeting_name},</p>
{"".join(sections)}
<p style="margin:16px 0 0;font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#2c3e50;">We'll keep watching, and we'll let you know when something else turns up.</p>
<p style="margin:8px 0 0;font-family:Georgia,'Times New Roman',serif;font-size:12px;color:#999;"><a href="{manage_url}" style="color:#999;">Manage your alerts</a></p>
<p style="margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;font-size:14px;color:#2c3e50;">Thanks for letting us help with the digging.</p>
"""
    body_html += _signoff_html(base_url)
    return _digest_subject(groups), _branded_wrapper(body_html, base_url)


async def send_search_alert_digest(
    to: str, *, first_name: Optional[str], groups: list
) -> bool:
    subject, body = compose_search_alert_digest(first_name=first_name, groups=groups)
    return await _send(to, subject, body)


async def send_youtube_transcript_report(
    to: str, *, ingested: list, skipped: list, failed: list
) -> bool:
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
        rows = "".join(
            f"<li>{html.escape(item['slug'])}: {html.escape(item['detail'])}</li>"
            for item in failed
        )
        body += f"<p><strong>{len(failed)} failed:</strong></p><ul>{rows}</ul>"
    if skipped:
        rows = "".join(
            f"<li>{html.escape(item['slug'])}: {html.escape(item['detail'])}</li>"
            for item in skipped
        )
        body += f"<p>{len(skipped)} skipped:</p><ul>{rows}</ul>"

    subject = (
        f"YouTube transcripts: {len(ingested)} added"
        if ingested
        else "YouTube transcripts: none new today"
    )
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


# A genuinely bad day should still produce a readable email. The
# 2026-08-23 Cablecast cluster was 33 failures; a thousand-row table is
# not a digest, and the dropped count below keeps a truncated one from
# understating the day.
MAX_FAILURES_LISTED = 40


def _render_failure_digest(failures: list) -> str:
    """The failure section of the daily worker report: every job that hit
    "failed" in the last 24h, grouped by reason, each row linking both the
    Archive page and the source URL that actually failed.

    Grouped by reason rather than listed flat because that is how these
    actually arrive -- one upstream cause producing a run of jobs (a
    platform-wide seek bug, an adapter resolving the wrong meeting, a
    plausibility gate firing on a batch of short clips). A flat
    newest-first list buries that shape; the grouping surfaces it in the
    subject-line glance.

    Reasons are used verbatim as the group key. They come from a small
    fixed set of literals the worker writes (see worker/main.py's _fail()
    calls and media_probe.py's own reason strings), so this groups cleanly
    without any parsing or normalisation -- and if a new reason string
    appears, it simply becomes its own group rather than being silently
    lumped in with an existing one.
    """
    if not failures:
        return (
            "<h2>Failures, last 24 hours</h2>"
            '<p style="color:#2e7d32">None. Every job that finished, finished cleanly.</p>'
        )

    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    by_reason: dict = {}
    for f in failures:
        by_reason.setdefault(f["error_message"], []).append(f)

    parts = [
        f"<h2>Failures, last 24 hours ({len(failures)})</h2>",
        '<p style="color:#666">Grouped by reason, most common first. '
        "Includes failures that never send their own email — anything that "
        "died before a chunk was attempted (no media found, unreadable "
        "media, implausible duration) is invisible in your inbox otherwise."
        "</p>",
    ]
    listed = 0
    for reason, jobs in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        parts.append(
            f'<h3 style="margin-bottom:4px">{html.escape(reason)} '
            f'<span style="font-weight:normal;color:#666">({len(jobs)})</span></h3>'
        )
        parts.append('<ul style="margin-top:0">')
        for j in jobs:
            if listed >= MAX_FAILURES_LISTED:
                break
            listed += 1
            title = html.escape(j.get("title") or j.get("slug") or "(untitled)")
            page = (
                f'<a href="{base_url}/m/{html.escape(j["slug"])}">{title}</a>'
                if base_url and j.get("slug")
                else title
            )
            src = html.escape(j.get("source_url") or "")
            # The chunk counter is the fastest way to tell the two failure
            # classes apart at a glance: 0/1 is a resolve-stage rejection
            # (nothing was ever attempted), anything else got into real
            # chunk processing.
            progress = f"{j.get('chunks_completed')}/{j.get('total_chunks')}"
            parts.append(
                f"<li>{page} "
                f'<span style="color:#666">[{html.escape(j.get("platform") or "?")}, '
                f"chunks {progress}, job {j.get('job_id')}]</span><br>"
                f'<a href="{src}" style="font-size:90%;color:#666">{src}</a></li>'
            )
        parts.append("</ul>")
        if listed >= MAX_FAILURES_LISTED:
            break

    dropped = len(failures) - listed
    if dropped > 0:
        parts.append(
            f'<p style="color:#666"><em>…and {dropped:,} more not listed '
            f"(showing the first {MAX_FAILURES_LISTED}).</em></p>"
        )
    return "".join(parts)


async def send_worker_daily_report(
    to: str,
    *,
    summary: dict,
    previous: Optional[dict],
    failures: Optional[list] = None,
) -> bool:
    """Daily activity digest for the transcription worker(s) -- see
    archive/main.py's GET /internal/send-worker-daily-report, triggered by
    .github/workflows/worker-daily-report.yml. Same "internal ops
    notification, plain HTML, sent every day even when nothing happened"
    pattern as send_youtube_transcript_report() above -- silence itself
    should never be the only signal a scheduled job stopped firing.

    `chunks_completed_last_24h` is None (rendered as "n/a (first report)")
    only on the very first-ever send, when there's no previous snapshot to
    diff against -- every subsequent send has a real number.

    `failures` (WO-46, 2026-08-23) is crud.list_recent_transcription_
    failures()'s output, rendered by _render_failure_digest() above.
    Defaults to None -- treated as "no failures section requested", which
    keeps every existing caller and test working unchanged -- while an
    explicit empty list renders a real "none, all clean" line. That
    distinction matters: silence should never be the only signal, which is
    the same reason this report sends daily even when nothing happened.
    """
    chunks_24h = (
        summary["cumulative_chunks_completed_all_time"]
        - previous["cumulative_chunks_completed"]
        if previous is not None
        else None
    )
    chunks_24h_str = (
        f"{chunks_24h:,}" if chunks_24h is not None else "n/a (first report)"
    )
    segments_24h = summary["segments_added_last_24h"]
    segments_24h_str = f"{segments_24h:,}" if segments_24h is not None else "n/a"

    body = (
        "<h2>Transcription worker activity, last 24 hours</h2>"
        '<table cellpadding="6" style="border-collapse: collapse">'
        f"<tr><td>Chunks completed</td><td><strong>{chunks_24h_str}</strong></td></tr>"
        f"<tr><td>Jobs finished</td><td><strong>{summary['jobs_completed_last_24h']:,}</strong></td></tr>"
        f"<tr><td>Segments transcribed</td><td><strong>{segments_24h_str}</strong></td></tr>"
        "</table>"
        "<h2>Current queue</h2>"
        '<table cellpadding="6" style="border-collapse: collapse">'
        f"<tr><td>Active jobs</td><td><strong>{summary['active_jobs']:,}</strong></td></tr>"
        f"<tr><td>Remaining chunks in active jobs</td><td><strong>{summary['remaining_chunks_in_active_jobs']:,}</strong></td></tr>"
        f"<tr><td>Meetings on the site with no transcript</td><td><strong>{summary['backlog_no_transcript']:,}</strong></td></tr>"
        f"<tr><td>Still in the tier-3 discovery queue (not yet archived)</td><td><strong>{summary['tier3_queue_remaining']:,}</strong></td></tr>"
        "</table>"
        f'<p style="color:#666">All-time cumulative: {summary["cumulative_chunks_completed_all_time"]:,} chunks, '
        f"{summary['cumulative_jobs_completed_all_time']:,} jobs completed.</p>"
    )
    if failures is not None:
        body += _render_failure_digest(failures)
    return await _send(to, "Transcription worker daily report", body)
