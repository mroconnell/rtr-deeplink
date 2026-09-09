"""Per-meeting inventory rows behind GET /internal/meeting-inventory
(WO-124, 2026-09-09) -- one flat row per archived page answering, for a
human review pass: what the page calls its government, what the registry
calls it, whether those agree and follow the "City, ST" convention, what
meeting body is stored, whether video and a transcript exist, and which
platform the page and the video each sit on.

Deliberately REPORTS, never guesses. Every column is either a stored
value, a value the site itself derives for display (effective_jurisdiction,
the /coverage platform split, the outcome bucket), or a plain comparison
of two of those. `meeting_body` in particular is the stored column and
nothing else -- a blank there is a real finding this report exists to
count (the first full run, 2026-09-09, had it blank on ~90% of 6,529
pages), not something to paper over with a title regex.

The input shape is one dict from crud.list_pages_for_export() (the light
form, no segments), so the endpoint and the export script share one read
path with /internal/export/pages.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Optional
from urllib.parse import urlparse

from app.utils.gov_registry import display_name as gov_display_name
from app.utils.gov_registry import government_for_id

from ..db import crud
from .jurisdiction_format import state_abbr_from_jurisdiction

PUBLIC_BASE = "https://redtaperecordings.com"

# Column order for both the JSON rows and the CSV. Grouped the way the
# review page bands them: government, meeting, media, platforms, links.
COLUMNS: tuple[str, ...] = (
    "page_id",
    "stored_jurisdiction",
    "page_display_name",
    "gov_id",
    "gov_display_name",
    "names_match",
    "follows_city_st",
    "gov_type",
    "jurisdiction_confidence",
    "meeting_body",
    "meeting_name",
    "meeting_date",
    "has_video",
    "video_format",
    "has_transcript",
    "transcript_source",
    "transcript_segments",
    "transcript_warnings",
    "outcome",
    "page_platform",
    "page_platform_by_url",
    "stored_platform",
    "best_effort_resolve",
    "video_platform",
    "video_host_domain",
    "archive_url",
    "source_url",
    "video_url",
    "created_at",
)

_CANADA_SUFFIX = " (Canada)"
# A stored name that only differs from the registry's by a leading entity
# phrase ("City of Napa, CA" vs "Napa, CA") is reported as "prefix only"
# rather than "no": the page already displays the registry form, so the
# stored string is stale, not wrong about which government it names.
_LEADING_ENTITY = re.compile(
    r"^(?:the\s+)?(?:city|town|village|county|township|borough|municipality)"
    r"\s+of\s+",
    re.IGNORECASE,
)
_CITY_ST = re.compile(r"^[^,]+, [A-Z]{2}$")


def _strip_canada(text: Optional[str]) -> str:
    return (text or "").replace(_CANADA_SUFFIX, "")


def names_match(stored: Optional[str], gov_id: Optional[str], gov_display: str) -> str:
    """ "yes" / "prefix only" / "no" / "no gov_id". Compares the STORED
    jurisdiction string to the registry's display name, not the page's
    displayed label -- that label is itself derived from gov_id, so
    comparing it would always say yes."""
    if not gov_id:
        return "no gov_id"
    if not gov_display:
        # gov_id set but not in the committed registry -- a minted or
        # since-removed id. Worth seeing, so it's its own value.
        return "gov_id not in registry"
    stored = stored or ""
    if stored == gov_display:
        return "yes"
    if _LEADING_ENTITY.sub("", stored).lower() == gov_display.lower():
        return "prefix only"
    return "no"


def follows_city_st(display: Optional[str]) -> str:
    """ "yes" when the displayed name is exactly "<name>, <ST>" with a real
    US-state or Canadian-province abbreviation (the " (Canada)" marker
    the page appends is ignored)."""
    base = _strip_canada(display)
    if _CITY_ST.match(base) and state_abbr_from_jurisdiction(base):
        return "yes"
    return "no"


def platform_by_url(source_url: str) -> str:
    """What app/platforms/base.py's detect_platform() says about the
    source URL TODAY, next to the platform stored at ingest -- the two
    differ for a wrapper page (a ProudCity or CivicWeb page whose stored
    platform is the delegated "youtube") and for a page ingested before
    its adapter existed. Lazy import: the archive service never needs the
    adapter package loaded otherwise."""
    try:
        from app.platforms.base import detect_platform
    except Exception:  # pragma: no cover - adapter package unavailable
        return ""
    try:
        return detect_platform(source_url) or ""
    except Exception:
        return ""


def inventory_row(page: dict) -> dict:
    """One flat inventory row from one crud.list_pages_for_export() dict."""
    gov_id = page.get("gov_id") or ""
    gov = government_for_id(gov_id) if gov_id else None
    gov_display = gov_display_name(gov) if gov else ""
    page_display = (
        crud.effective_jurisdiction(gov_id or None, page.get("jurisdiction")) or ""
    )

    versions = page.get("versions") or []
    default = next((v for v in versions if v.get("is_default")), None)
    segments = int((default or {}).get("segment_count") or 0)
    warnings = (default or {}).get("transcript_warnings") or []
    has_transcript = segments > 0

    video_url = page.get("video_url") or ""
    source_url = page.get("source_url_normalized") or ""
    detail_label, video_label = crud._platform_split(
        page.get("platform") or "", source_url, video_url or None
    )
    outcome = crud._classify_page_outcome(
        video_url=video_url or None,
        agenda_items=page.get("agenda_items"),
        default_content_hash=(default or {}).get("content_hash"),
        default_transcript_warnings=warnings,
        default_transcript_language=(default or {}).get("language"),
    )

    return {
        "page_id": page["id"],
        "stored_jurisdiction": page.get("jurisdiction") or "",
        "page_display_name": page_display,
        "gov_id": gov_id,
        "gov_display_name": gov_display,
        "names_match": names_match(page.get("jurisdiction"), gov_id, gov_display),
        "follows_city_st": follows_city_st(page_display),
        "gov_type": page.get("gov_type") or "",
        "jurisdiction_confidence": page.get("jurisdiction_confidence") or "",
        "meeting_body": page.get("meeting_body") or "",
        "meeting_name": page.get("title") or "",
        "meeting_date": page.get("date") or "",
        "has_video": "yes" if video_url else "no",
        "video_format": page.get("video_format") or "",
        "has_transcript": "yes" if has_transcript else "no",
        "transcript_source": (default or {}).get("source", "")
        if has_transcript
        else "",
        "transcript_segments": segments,
        "transcript_warnings": len(warnings),
        "outcome": crud._OUTCOME_LABELS.get(outcome, outcome),
        "page_platform": detail_label,
        "page_platform_by_url": platform_by_url(source_url),
        "stored_platform": page.get("platform") or "",
        "best_effort_resolve": "yes" if page.get("best_effort") else "no",
        "video_platform": video_label if video_url else "",
        "video_host_domain": urlparse(video_url).netloc if video_url else "",
        "archive_url": f"{PUBLIC_BASE}/m/{page['slug']}",
        "source_url": source_url,
        "video_url": video_url,
        "created_at": page.get("created_at") or "",
    }


def rows_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(COLUMNS), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
