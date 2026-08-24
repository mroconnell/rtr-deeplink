"""Meeting-date status for the "Upcoming" / "Recent" pills on /meetings
and the matching notice on a permanent meeting page.

Why this exists (Ryan, 2026-08-17): a page with no transcript reads as a
gap, but for a meeting that hasn't happened yet, or happened days ago,
it's just *early* -- government caption pipelines routinely publish video
and captions days to weeks after the meeting (the same reality
ARCHIVE_RECHECK_AFTER in app/main.py is built on). Labeling those pages
honestly stops them looking broken and tells a visitor to check back.

Pure (no I/O, no DB, no app imports) so it's trivially unit-testable
with a pinned `today`; the callers pass real UTC "today". Stdlib apart
from markupsafe, which meeting_date_html() below needs -- that function
moved here from archive/main.py in WO-50 so `archive/db/crud.py` could
pre-render a meeting's date for the shared featured-card partial without
importing archive.main. Meeting dates are stored as
local-to-the-meeting "YYYY-MM-DD" strings with no timezone, so comparing
against a UTC date can be off by at most one calendar day around
midnight -- acceptable for a soft label, not worth a timezone lookup.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from markupsafe import Markup, escape

# How long after the meeting date a transcript-less page is still labeled
# "Recent" (captions may still be on their way) rather than left as a
# plain gap. 30 days, matching ARCHIVE_RECHECK_AFTER's "government
# caption pipelines can take weeks" reasoning -- a judgment call, not a
# measured figure; tune here if real data says otherwise.
RECENT_MEETING_WINDOW = timedelta(days=30)

UPCOMING = "upcoming"
RECENT = "recent"


def parse_meeting_date(raw: Optional[str]) -> Optional[date]:
    """Tolerant parse of MeetingPage.date. The app writes ISO
    "YYYY-MM-DD", but the column is a free String(20) that older/odd
    ingests may have filled differently -- anything unparseable is
    treated as "no date" rather than raised."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def iso_meeting_date(raw: Optional[str]) -> Optional[str]:
    """Normalized "YYYY-MM-DD" for a MeetingPage.date, or None if it isn't
    a real, parseable date.

    Two template jobs, both needing exactly this guarantee (2026-08-21):

    1. `<time datetime="...">` on visible meeting dates -- a `datetime`
       attribute that isn't a valid HTML date string is worse than no
       `<time>` element at all, so the templates fall back to plain text
       when this returns None.
    2. The VideoObject `uploadDate` / Event `startDate` JSON-LD on
       /m/{slug}, which used to interpolate `page.date` verbatim. That's
       the direct, fixable-now half of Google Search Console's `uploadDate`
       "invalid datetime value" flag (BACKLOG.md): every adapter today is
       structurally constrained to emit "YYYY-MM-DD" or None (they all go
       through strftime("%Y-%m-%d") or an anchored ISO regex), but nothing
       between an adapter and this template ever *validated* that --
       `date` is a free `Optional[str]` on ResolvedMeeting, on
       IngestRequest, and as a String(20) column -- so any older row, or
       any push from a script, could carry something else straight into
       the emitted markup. Now it can't.

    Deliberately reuses parse_meeting_date's tolerance rather than a strict
    regex, so a value like "2026-08-03T00:00:00" is *normalized* to
    "2026-08-03" instead of dropped -- fixing such a row's markup rather
    than silently omitting the field.
    """
    parsed = parse_meeting_date(raw)
    return parsed.isoformat() if parsed else None


def meeting_date_status(
    raw_date: Optional[str],
    *,
    has_transcript: bool,
    today: Optional[date] = None,
) -> Optional[str]:
    """Returns UPCOMING if the meeting date is after `today`, RECENT if it
    is within RECENT_MEETING_WINDOW before (or on) `today` *and* the page
    has no transcript yet, else None.

    "Recent" is deliberately gated on has_transcript: once a transcript
    exists there's nothing to wait for, so the label would only be noise.
    "Upcoming" is not gated -- a future meeting with a pre-posted agenda
    is still upcoming, and that's exactly the case where the label helps
    ("why is there no video?"). A missing/unparseable date yields None.
    """
    meeting_date = parse_meeting_date(raw_date)
    if meeting_date is None:
        return None
    if today is None:
        today = datetime.now(timezone.utc).date()
    if meeting_date > today:
        return UPCOMING
    if not has_transcript and (today - meeting_date) <= RECENT_MEETING_WINDOW:
        return RECENT
    return None


def meeting_date_html(raw: Optional[str]) -> Markup:
    """A visible meeting date wrapped in semantic `<time datetime="...">`
    (2026-08-21, CLAUDE_BACKLOG.md's SEO/accessibility Tier 3 item -- this
    codebase previously had no `<time>` markup anywhere), falling back to
    the plain text when the stored date isn't parseable: a `datetime`
    attribute that isn't a valid HTML date string is worse than no `<time>`
    element at all.

    One filter rather than an inline `{% if %}` repeated across the five
    templates that render a meeting date, so the fallback branch can't
    drift between them -- and so it's unit-testable directly. Markup.format
    escapes its arguments, so an odd stored `date` string can't inject
    markup through the visible half.
    """
    iso = iso_meeting_date(raw)
    if not iso:
        return Markup(escape(raw or ""))
    return Markup('<time datetime="{}">{}</time>').format(iso, raw)
