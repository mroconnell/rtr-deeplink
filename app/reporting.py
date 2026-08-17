"""Once-a-day operator digest: Clerk user counts, Resend send/subscriber
counts, and how many report/resolve requests this service handled -- all
live reads against existing systems, no new persistence anywhere.

Lives here (importable from both GET /admin/daily-report below and
scripts/daily_report.py's CLI wrapper) rather than being duplicated in
each, since the metric-fetching/composition logic has exactly one real
implementation either way.

"Reports run" = total meeting_resolutions rows in the last 24h, with no
per-user breakdown -- that table has no user/session linkage at all today
(resolves are fully anonymous at the DB level even when the requester was
signed in), and wiring Clerk auth into /api/resolve to add that is out of
scope for this basic-reporting pass.

Resend has no concept of "emails received" (it's send-only) and its List
Emails endpoint has no date-range filter, so "sent in the last 24h" means
paging recent results and filtering by created_at client-side, same
personal-scale "a full scan is fine" reasoning app/db/crud.py's own
get_stats() already documents for meeting_resolutions.

**Needs live verification against a real Resend account before trusting
in production** -- GET /emails and GET /audiences/{id}/contacts (list
form, not the existing single-contact lookup in
archive/utils/email.py's check_audience_membership()) are both new paths
in this codebase. Live-verified once already (2026-08-11, via
scripts/daily_report.py --dry-run against the real account): both
endpoints returned real, plausible counts with the assumed
`data`/`has_more`/per-item `id`/`created_at` shape -- see BACKLOG_DONE.md
if that entry exists, or this comment stands as the record otherwise.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import aiohttp

from .db import crud

logger = logging.getLogger("rtr_deeplink.reporting")

_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Safety net against an unbounded page-walk if either Resend list endpoint
# ever turns out not to be newest-first after all (Clerk's docs say it is;
# Resend's don't say either way) -- at personal-scale send/signup volume
# this is never expected to actually bind.
_MAX_PAGES = 20


@dataclass
class MetricResult:
    """Lets one metric fail without blanking out the others -- a once-a-day
    digest should still report what it *could* get, not go silent because
    one of three independent APIs had a bad moment."""

    value: Optional[int]
    error: Optional[str] = None


def _fmt(result: MetricResult) -> str:
    if result.error is not None:
        return f"unavailable ({result.error})"
    return str(result.value)


def _metrics_to_jsonable(metrics: dict) -> dict:
    """MetricResult isn't a Pydantic model, so build the JSON-safe shape
    explicitly rather than relying on FastAPI's encoder to guess."""
    return {name: {"value": r.value, "error": r.error} for name, r in metrics.items()}


def failed_metric_names(jsonable_metrics: dict) -> list:
    """Which metrics in the (already-jsonable) dict came back with an
    error. Used by GET /admin/daily-report (WO-7, 2026-08-16) to decide
    whether to return a non-2xx -- previously a metric failing silently
    composed into the email as "unavailable (...)" with no signal at the
    HTTP layer, so the cron's `--fail-with-body` never tripped and a
    degraded report looked identical to a healthy one from the outside."""
    return [name for name, m in jsonable_metrics.items() if m.get("error") is not None]


async def fetch_clerk_metrics(secret_key: str) -> dict:
    """Returns {"clerk_total_users": MetricResult, "clerk_new_users_24h": MetricResult}."""
    if not secret_key:
        missing = MetricResult(None, "CLERK_SECRET_KEY not set")
        return {"clerk_total_users": missing, "clerk_new_users_24h": missing}

    from clerk_backend_api import Clerk

    try:
        cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000
        )
        async with Clerk(bearer_auth=secret_key) as clerk:
            total = await clerk.users.count_async(request={})
            new = await clerk.users.count_async(request={"created_at_after": cutoff_ms})
        return {
            "clerk_total_users": MetricResult(total.total_count),
            "clerk_new_users_24h": MetricResult(new.total_count),
        }
    except Exception as e:
        error = f"{type(e).__name__}: {str(e)[:200]}"
        failed = MetricResult(None, error)
        return {"clerk_total_users": failed, "clerk_new_users_24h": failed}


async def _resend_get(session: aiohttp.ClientSession, url: str, api_key: str) -> dict:
    async with session.get(
        url, headers={"Authorization": f"Bearer {api_key}"}, timeout=_TIMEOUT
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise RuntimeError(
                f"Resend GET {url} failed ({response.status}): {text[:200]}"
            )
        return await response.json()


async def _count_since(
    session: aiohttp.ClientSession, url: str, api_key: str, cutoff: datetime
) -> int:
    """Pages a Resend list endpoint (?limit=100&after=<cursor>), counting
    items whose created_at falls within the window and stopping once a
    page's items are all older than cutoff -- relies on the endpoint being
    sorted newest-first, guarded by _MAX_PAGES in case that assumption
    turns out wrong for one of these two endpoints specifically.
    """
    count = 0
    after = None
    for _ in range(_MAX_PAGES):
        page_url = f"{url}?limit=100"
        if after:
            page_url += f"&after={after}"
        data = await _resend_get(session, page_url, api_key)
        items = data.get("data", [])
        if not items:
            break

        stop = False
        for item in items:
            created_at = item.get("created_at")
            if not created_at:
                continue
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created >= cutoff:
                count += 1
            else:
                stop = True
                break

        if stop or not data.get("has_more"):
            break
        after = items[-1].get("id")
        if not after:
            break

    return count


async def fetch_resend_sent_count(api_key: str) -> MetricResult:
    if not api_key:
        return MetricResult(None, "RESEND_API_KEY not set")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    try:
        async with aiohttp.ClientSession() as session:
            count = await _count_since(
                session, "https://api.resend.com/emails", api_key, cutoff
            )
        return MetricResult(count)
    except Exception as e:
        return MetricResult(None, f"{type(e).__name__}: {str(e)[:200]}")


async def fetch_resend_new_subscriber_count(
    api_key: str, audience_id: str
) -> MetricResult:
    if not api_key or not audience_id:
        return MetricResult(None, "RESEND_API_KEY/RESEND_AUDIENCE_ID not set")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    try:
        async with aiohttp.ClientSession() as session:
            count = await _count_since(
                session,
                f"https://api.resend.com/audiences/{audience_id}/contacts",
                api_key,
                cutoff,
            )
        return MetricResult(count)
    except Exception as e:
        return MetricResult(None, f"{type(e).__name__}: {str(e)[:200]}")


async def fetch_reports_run_count() -> MetricResult:
    try:
        return MetricResult(await crud.count_recent_resolutions(hours=24))
    except Exception as e:
        return MetricResult(None, f"{type(e).__name__}: {str(e)[:200]}")


def compose_report_email(metrics: dict, *, report_date: date) -> tuple:
    """Returns (subject, html_body). Plain internal-ops HTML -- this is a
    digest for Ryan, not a subscriber-facing send, so no branded wrapper
    or unsubscribe footer (matches send_youtube_transcript_report()'s
    style in archive/utils/email.py, not app/main.py's _branded_email_html()'s)."""
    reports_run = metrics["reports_run"]
    new_users = metrics["clerk_new_users_24h"]
    headline = f"{_fmt(reports_run)} reports run, {_fmt(new_users)} new users"
    subject = f"Daily report {report_date.isoformat()}: {headline}"

    body = f"""\
<p><strong>Clerk users</strong></p>
<ul>
  <li>Total: {_fmt(metrics["clerk_total_users"])}</li>
  <li>New in last 24h: {_fmt(metrics["clerk_new_users_24h"])}</li>
</ul>
<p><strong>Resend</strong></p>
<ul>
  <li>Emails sent in last 24h: {_fmt(metrics["resend_sent_24h"])}</li>
  <li>New subscribers in last 24h: {_fmt(metrics["resend_new_subscribers_24h"])}</li>
</ul>
<p><strong>Reports run</strong></p>
<ul>
  <li>Resolve attempts in last 24h: {_fmt(metrics["reports_run"])}</li>
</ul>
"""
    return subject, body


async def send_report_email(
    to: str, subject: str, body_html: str, *, api_key: str, from_address: str
) -> bool:
    """Minimal Resend transactional send -- deliberately a third copy of
    the ~15-line POST /emails pattern already independently duplicated in
    app/main.py's _resend_send() and archive/utils/email.py's _send(),
    rather than importing either: both are private, and archive's version
    would silently attach an unsubscribe footer that's wrong for a
    single-recipient internal ops email. app/main.py's _resend_send() is
    close enough (also no unsubscribe footer needed here since ops
    recipients aren't subscribers) but is private to that module and
    already handles a broader multi-purpose call shape (cc, footer
    toggle) this single-purpose sender doesn't need.
    """
    if not api_key or not from_address:
        logger.error(
            "Daily report send attempted but RESEND_API_KEY/RESEND_FROM_ADDRESS isn't configured."
        )
        return False

    payload = {"from": from_address, "to": [to], "subject": subject, "html": body_html}
    reply_to = os.environ.get("RESEND_REPLY_TO_ADDRESS", "")
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=_TIMEOUT,
            ) as response:
                if response.status < 300:
                    return True
                logger.error(
                    "Daily report send failed (%s): %s",
                    response.status,
                    await response.text(),
                )
                return False
    except Exception:
        logger.exception("Daily report send request failed.")
        return False


async def gather_metrics() -> dict:
    import asyncio

    clerk_secret = os.environ.get("CLERK_SECRET_KEY", "")
    resend_api_key = os.environ.get("RESEND_API_KEY", "")
    resend_audience_id = os.environ.get("RESEND_AUDIENCE_ID", "")

    clerk_metrics, resend_sent, resend_subs, reports_run = await asyncio.gather(
        fetch_clerk_metrics(clerk_secret),
        fetch_resend_sent_count(resend_api_key),
        fetch_resend_new_subscriber_count(resend_api_key, resend_audience_id),
        fetch_reports_run_count(),
    )
    return {
        **clerk_metrics,
        "resend_sent_24h": resend_sent,
        "resend_new_subscribers_24h": resend_subs,
        "reports_run": reports_run,
    }


async def run_daily_report(*, to: str, dry_run: bool = False) -> dict:
    """Gathers every metric, composes the email, and (unless dry_run) sends
    it to `to`. Returns {"subject", "body", "sent"} either way -- the
    single entry point both GET /admin/daily-report (app/main.py) and
    scripts/daily_report.py's CLI wrapper call, so there's exactly one
    real implementation of "what does a daily report run do."
    """
    metrics = await gather_metrics()
    subject, body = compose_report_email(metrics, report_date=date.today())

    sent = False
    if not dry_run:
        resend_api_key = os.environ.get("RESEND_API_KEY", "")
        resend_from = os.environ.get("RESEND_FROM_ADDRESS", "")
        sent = await send_report_email(
            to, subject, body, api_key=resend_api_key, from_address=resend_from
        )

    return {
        "subject": subject,
        "body": body,
        "sent": sent,
        "metrics": _metrics_to_jsonable(metrics),
    }
