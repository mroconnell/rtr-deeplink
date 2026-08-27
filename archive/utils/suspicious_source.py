"""Detects a real, recurring failure shape: a vendor's own non-production
content (a staging/UAT tenant, a shared demo/seed post) getting ingested
as if it were a real government meeting.

Confirmed twice now, on two unrelated platforms -- worth a shared,
cross-adapter check rather than a third one-off patch:

1. Three PrimeGov UAT/staging tenant pages got real-ingested during a
   bulk gate-blindness recheck (2026-08-19) -- the reason
   `/internal/admin/delete-pages` exists at all.
2. ProudCity's shared `/meetings/example-city-council-meeting/` seed
   post -- present, identical, on every install -- got real-ingested
   twice (Santa Ana CA, Palmview TX, 2026-08-26) before
   `proudcity.py`'s own `_DEMO_SLUG_RE` caught it. That fix is real but
   platform-specific; this module is the systemic backstop for the NEXT
   platform that has the same shape and hasn't earned its own dedicated
   adapter (or check) yet.

Deliberately conservative: flags for review (forces `best_effort=True`,
the same low-trust-queue mechanism this repo already has -- see
`/internal/low-trust-pages`) rather than rejecting outright. A false
positive here just means a human looks at a real page once; a false
negative means fabricated content goes live with full trust, which is
the worse failure mode -- see the two incidents above.

Checks the URL only (hostname labels + path), never the title/content.
A meeting's own title can legitimately contain "test" ("COVID Testing
Site Task Force") or "demo" ("Product Demo Day Proclamation") -- real
government text, not a vendor's own non-production marker. A URL's
hostname or path essentially never does, which is what keeps the false-
positive rate low enough to act on automatically.
"""

import re
from urllib.parse import urlparse
from typing import Optional

# Subdomain labels a vendor's own non-production tenant is named with --
# matched as a whole hostname *label* (between dots), never a substring,
# so "testcounty.granicus.com" (a real county named "Test County" -- yes,
# these exist, e.g. Test, NC) isn't caught by accident the way a bare
# substring match would be.
_STAGING_LABEL_RE = re.compile(
    r"(?:^|\.)(?:uat|staging|stage|sandbox|demo|preprod|dev)(?:\.|$)",
    re.IGNORECASE,
)

# Known literal path segments confirmed to be shared vendor demo/seed
# content, not a real government's own page -- grow this list per real
# incident, the same way _KNOWN_DOMAINS/PROUDCITY_KNOWN_DOMAINS grow.
_KNOWN_DEMO_PATHS = (
    # ProudCity's shared wp-proud-meeting seed post (BACKLOG_DONE.md,
    # 2026-08-26) -- confirmed identical across 3 unrelated tenants.
    "/meetings/example-city-council-meeting",
)


def suspicious_source_reason(url: Optional[str]) -> Optional[str]:
    """Returns a short, human-readable reason if `url` looks like a
    vendor's own non-production content rather than a real government
    page, else None. Never raises on a malformed URL -- worst case is a
    missed flag, not a crash in the ingest path."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if _STAGING_LABEL_RE.search(host):
        return f"hostname {host!r} looks like a staging/UAT/demo tenant, not a production one"

    path = parsed.path.lower().rstrip("/")
    for known in _KNOWN_DEMO_PATHS:
        if path == known:
            return f"path {path!r} is a known shared vendor demo/seed page"

    return None
