"""WO-272 Stage 1: mine URLs we already hold for recurring path shapes.

Makes ZERO network requests. Reads three kinds of URL already on disk:

1. `~/Documents/rtr-business/research/jurisdiction_coverage.csv` --
   `example_meeting_url`, `example_agenda_or_calendar_url`,
   `alternate_urls` (semicolon-separated, may hold several URLs).
2. A one-time, read-only export of the Archive's own pages
   (`GET /internal/export/pages`, pulled separately by
   `wo272_fetch_export.py` in this session's private scratch directory
   and saved as JSONL) -- `source_url_normalized`. Every row here
   produced a real page with video, so its shape is proven.
3. `~/Documents/rtr-business/research/wo268_passive_pilot.csv`'s
   `candidate_hub_url` column and `wo268_hub_path_frequency.csv` --
   these come from governments where the access ladder found nothing,
   so they correct the survivorship bias in 1 and 2.

For every URL: split host and path, normalize the path into a template
(numeric ids / GUIDs / dates / long hex-or-base64 tokens become
placeholders, query-parameter NAMES are kept and values dropped,
lowercase throughout). Count templates by (host_family, template).
`host_family` is "vendor" when the host is a government's OWN recorded
domain's literal mismatch (real different host) AND either a known
vendor substring from `app/platforms/base.py`'s `detect_platform()` or
shared by >=3 distinct governments in this combined dataset; otherwise
"first-party". Each template is labeled:

- `known` if `detect_platform()` recognizes a REAL example URL of this
  template (run, not guessed).
- `meeting-shaped-unknown` if it recurs >=5 times across >=3 distinct
  hosts, carries a meeting/agenda/minutes/council/board/video/stream
  word, and `detect_platform()` returns "unknown".
- `first-party` for any remaining template on a government's own
  domain.
- `vendor-other` for a remaining template on a vendor-classified host
  that clears neither bar above (the residual bucket; not one of the
  three labels the WO brief named, added so every row gets exactly one
  label rather than leaving a gap -- see the investigation doc).

Writes `rtr-business/research/wo272_url_templates.csv` (and leaves the
government's git commit to the conductor, per CLAUDE.md's worktree
rule -- this script itself never runs `git`).
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse, parse_qsl

# Resolve relative to this file, not a hardcoded path -- this script
# lives in a git worktree, and a hardcoded main-checkout path silently
# imports a DIFFERENT (and, confirmed live 2026-09-12, older/behind)
# copy of app/platforms/base.py, which under-detects platforms like
# boxcast/wistia that this worktree's checkout already recognizes.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms.base import detect_platform  # noqa: E402

RTR_BUSINESS = Path("/Users/mroconnell/Documents/rtr-business/research")
JC_CSV = RTR_BUSINESS / "jurisdiction_coverage.csv"
WO268_PILOT_CSV = RTR_BUSINESS / "wo268_passive_pilot.csv"
WO268_FREQ_CSV = RTR_BUSINESS / "wo268_hub_path_frequency.csv"

SCRATCH = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-platform-detection-backfill-c9742a"
    "/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/agents/a7e73d38a61b93564"
)
ARCHIVE_EXPORT_JSONL = SCRATCH / "wo272_pages_export.jsonl"

OUT_CSV = RTR_BUSINESS / "wo272_url_templates.csv"

MEETING_WORDS = (
    "meeting",
    "agenda",
    "minutes",
    "council",
    "board",
    "video",
    "stream",
)

# Vendor hostname substrings detect_platform() itself checks (read from
# app/platforms/base.py, 2026-09-12) -- used only to help decide
# host_family; labeling a template `known` always re-runs
# detect_platform() on a real example URL rather than trusting this list
# on its own.
KNOWN_VENDOR_SUBSTRINGS = (
    "granicus.com",
    "legistar.com",
    "legistar.council.nyc.gov",
    "civicclerk.com",
    "civicplus.com",
    "civicplus",
    "primegov.com",
    "swagit.com",
    "escribemeetings.com",
    "destinyhosted.com",
    "civicweb.net",
    "diligentoneplatform.com",
    "telvue.com",
    "peg.tv",
    "viebit.com",
    "cablecast.tv",
    "clerkshq.com",
    "champds.com",
    "iqm2.com",
    "seattlechannel.org",
    "auroratv.org",
    "castus.tv",
    "townhallstreams.com",
    "open.media",
    "ompnetwork.org",
    "vimeo.com",
    "player.vimeo.com",
    "suiteonemedia.com",
    "hosted.civiclive.com",
    "hosted2.civiclive.com",
    "municodemeetings.com",
    "invintus.com",
    "hostedevents.invintus.com",
    "wistia.com",
    "wistia.net",
    "boxcast.tv",
    "youtube.com",
    "youtu.be",
    # Seen in the research file but not yet a rtr-deeplink adapter --
    # still real, known vendor products, so still "vendor" host_family.
    "laserfiche.com",
    "boarddocs.com",
    "simbli.net",
    "novusagenda.com",
    "mediasite.com",
    "hylandcloud.com",
    "databankcloud.com",
)

_NUMERIC_RE = re.compile(r"^\d+$")
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_GUID_NODASH_RE = re.compile(r"^[0-9a-f]{32}$")
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{4}\d{2}\d{2}|\d{2}-\d{2}-\d{4})$")
_LONG_HEX_RE = re.compile(r"^[0-9a-f]{16,}$")
_LONG_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")
_WORD_THEN_DIGITS_RE = re.compile(r"^([a-z]+)(\d{2,})$")


def _looks_like_plain_word(segment: str) -> bool:
    """A long alnum run that is plainly an English-ish word/slug, not a
    token -- all-lowercase-or-hyphen with no digits, even if long (e.g.
    a 30-char agenda-item slug). Long base64/hex tokens always mix case
    or digits; a real word slug usually doesn't."""
    return bool(re.fullmatch(r"[a-z-]+", segment))


def normalize_path(path: str) -> str:
    path = path.lower()
    segments = [s for s in path.split("/") if s != ""]
    out = []
    for seg in segments:
        if _NUMERIC_RE.match(seg):
            out.append("{id}")
            continue
        if _GUID_RE.match(seg) or _GUID_NODASH_RE.match(seg):
            out.append("{guid}")
            continue
        if _DATE_RE.match(seg):
            out.append("{date}")
            continue
        if _LONG_HEX_RE.match(seg):
            out.append("{token}")
            continue
        if _LONG_TOKEN_RE.match(seg) and not _looks_like_plain_word(seg):
            out.append("{token}")
            continue
        m = _WORD_THEN_DIGITS_RE.match(seg)
        if m:
            out.append(f"{m.group(1)}{{id}}")
            continue
        out.append(seg)
    return "/" + "/".join(out)


def normalize_url(url: str) -> tuple[str, str] | None:
    """Returns (host, template) or None if the URL can't be parsed."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    template_path = normalize_path(parsed.path)
    if parsed.query:
        names = sorted({k.lower() for k, _ in parse_qsl(parsed.query)})
        template = template_path + "?" + "&".join(names)
    else:
        template = template_path
    return host, template


def load_jc_rows():
    """Yields (source, url, gov_key, domain) tuples from the research
    file's three URL columns."""
    with JC_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gov_key = row.get("gov_id") or row.get("domain") or row.get("city_name")
            domain = (row.get("domain") or "").strip().lower()
            urls = []
            for col in ("example_meeting_url", "example_agenda_or_calendar_url"):
                v = (row.get(col) or "").strip()
                if v:
                    urls.append(v)
            alt = (row.get("alternate_urls") or "").strip()
            if alt:
                for piece in alt.split(";"):
                    piece = piece.strip()
                    if piece.startswith("http"):
                        urls.append(piece)
            for u in urls:
                yield "jc_csv", u, gov_key, domain


def load_archive_export_rows():
    if not ARCHIVE_EXPORT_JSONL.exists():
        print(
            f"WARNING: {ARCHIVE_EXPORT_JSONL} not found -- run "
            "wo272_fetch_export.py first. Skipping source 2.",
            file=sys.stderr,
        )
        return
    with ARCHIVE_EXPORT_JSONL.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            url = row.get("source_url_normalized")
            if not url:
                continue
            gov_key = row.get("gov_id") or f"page:{row.get('id')}"
            yield "archive_export", url, gov_key, None


def load_wo268_passive_rows():
    if not WO268_PILOT_CSV.exists():
        print(
            f"NOTE: {WO268_PILOT_CSV} not found -- WO-268 has not landed, "
            "skipping source 3 (passive pilot). ",
            file=sys.stderr,
        )
        return
    with WO268_PILOT_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            url = (row.get("candidate_hub_url") or "").strip()
            if not url:
                continue
            gov_key = row.get("gov_id") or row.get("domain")
            domain = (row.get("domain") or "").strip().lower()
            yield "wo268_passive", url, gov_key, domain


def load_wo268_freq_rows():
    """These are already aggregated first-path-segment counts from
    WO-268's 300-government sample, not individual URLs -- kept as a
    separate, coarser-granularity source (see module docstring)."""
    if not WO268_FREQ_CSV.exists():
        print(
            f"NOTE: {WO268_FREQ_CSV} not found -- skipping source wo268_hub_freq.",
            file=sys.stderr,
        )
        return []
    rows = []
    with WO268_FREQ_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def main():
    # Pass 1: collect raw (source, host, template, gov_key, example_url)
    raw = []
    host_gov_keys = defaultdict(set)
    jc_domain_by_govkey = {}

    for source, url, gov_key, domain in load_jc_rows():
        if domain:
            jc_domain_by_govkey.setdefault(gov_key, domain)
        norm = normalize_url(url)
        if norm is None:
            continue
        host, template = norm
        host_gov_keys[host].add(gov_key)
        raw.append((source, host, template, gov_key, url, domain))

    for source, url, gov_key, domain in load_archive_export_rows():
        norm = normalize_url(url)
        if norm is None:
            continue
        host, template = norm
        host_gov_keys[host].add(gov_key)
        raw.append((source, host, template, gov_key, url, domain))

    for source, url, gov_key, domain in load_wo268_passive_rows():
        norm = normalize_url(url)
        if norm is None:
            continue
        host, template = norm
        host_gov_keys[host].add(gov_key)
        raw.append((source, host, template, gov_key, url, domain))

    print(
        f"Collected {len(raw)} normalized URL rows across sources 1-3.", file=sys.stderr
    )

    def is_known_vendor_host(host: str) -> bool:
        return any(sub in host for sub in KNOWN_VENDOR_SUBSTRINGS)

    def host_family(host: str, domain: str | None, gov_key) -> str:
        # 1. Explicit own-domain match -> first-party, always.
        own_domain = domain or jc_domain_by_govkey.get(gov_key)
        if own_domain:
            if host == own_domain or host.endswith("." + own_domain):
                return "first-party"
        # 2. A literally-known vendor host -> vendor.
        if is_known_vendor_host(host):
            return "vendor"
        # 3. Data-driven fallback: a host shared by >=3 distinct
        #    governments in this combined dataset is a shared tenant
        #    host even if we don't have a name for the vendor.
        if len(host_gov_keys.get(host, ())) >= 3:
            return "vendor"
        # 4. Default: a government's own, otherwise-unclassified domain.
        return "first-party"

    # Pass 2: group by (source, host_family, template)
    groups = defaultdict(
        lambda: {"rows": 0, "govs": set(), "hosts": set(), "example": None}
    )
    for source, host, template, gov_key, url, domain in raw:
        fam = host_family(host, domain, gov_key)
        key = (source, fam, template)
        g = groups[key]
        g["rows"] += 1
        g["govs"].add(gov_key)
        g["hosts"].add(host)
        if g["example"] is None:
            g["example"] = url

    # Pass 3: label each (source, host_family, template) group.
    out_rows = []
    for (source, fam, template), g in groups.items():
        example = g["example"]
        platform = detect_platform(example)
        known = platform != "unknown"
        if known:
            label = "known"
        else:
            has_word = any(w in template for w in MEETING_WORDS)
            recurs_enough = g["rows"] >= 5 and len(g["hosts"]) >= 3
            if has_word and recurs_enough:
                label = "meeting-shaped-unknown"
            elif fam == "first-party":
                label = "first-party"
            else:
                label = "vendor-other"
        out_rows.append(
            {
                "source": source,
                "host_family": fam,
                "template": template,
                "platform_label": platform,
                "known_to_resolver": known,
                "rows": g["rows"],
                "distinct_govs": len(g["govs"]),
                "distinct_hosts": len(g["hosts"]),
                "example_url": example,
                "label": label,
            }
        )

    # Append the coarser wo268_hub_freq rows, kept separate, no
    # distinct_govs/distinct_hosts data available at that granularity.
    for row in load_wo268_freq_rows():
        pattern = row.get("path_pattern", "")
        example = row.get("example_url", "")
        platform = detect_platform(example) if example else "unknown"
        known = platform != "unknown"
        has_word = any(w in pattern.lower() for w in MEETING_WORDS)
        try:
            count = int(row.get("count") or 0)
        except ValueError:
            count = 0
        if known:
            label = "known"
        elif has_word and count >= 5:
            label = "meeting-shaped-unknown"
        else:
            label = "first-party"
        out_rows.append(
            {
                "source": "wo268_hub_freq",
                "host_family": "first-party",
                "template": pattern,
                "platform_label": platform,
                "known_to_resolver": known,
                "rows": count,
                "distinct_govs": "",
                "distinct_hosts": "",
                "example_url": example,
                "label": label,
            }
        )

    out_rows.sort(key=lambda r: (r["source"], -r["rows"]))

    with OUT_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source",
                "host_family",
                "template",
                "platform_label",
                "known_to_resolver",
                "rows",
                "distinct_govs",
                "distinct_hosts",
                "example_url",
                "label",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in out_rows:
            writer.writerow(row)

    print(f"Wrote {len(out_rows)} template rows to {OUT_CSV}", file=sys.stderr)

    # Summary for quick sanity-check in the terminal.
    by_label = defaultdict(int)
    for row in out_rows:
        by_label[row["label"]] += 1
    print("Label counts:", dict(by_label), file=sys.stderr)


if __name__ == "__main__":
    main()
