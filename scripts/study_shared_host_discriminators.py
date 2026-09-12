"""Study which per-host discriminator (YouTube channel, Vimeo owner, TelVue
org token, ClerkBase site slug, ...) each government in the Archive is
actually using, and turn every 1:1 finding into a candidate
`tenant_overrides.csv` rule.

Why (gov-id audit, 2026-09-09): a shared host -- one `tenant_host` serving
many governments -- cannot be pinned by host alone. `tenant_overrides.csv`
already has a `match` column for the finer detail and `resolver.
_match_override()` already honours three shapes (path fragment, `key=value`
in the query string, `key=value` in `page_hints`). What was missing was the
DATA: 56 YouTube pins bound one video each, and 33 TelVue pins were keyed
on `playlists/N` while 80 of the 96 archived TelVue pages carry
`/player/<token>/media/N` with no playlist at all, so they never match.
The Archive already holds ~1,560 YouTube-backed pages whose government is
solidly known; asking each video who posted it yields the channel -> gov
map for free, and the same trick works for every other shared host.

What it reads: `GET /internal/export/pages` (metadata only, no segments),
either live (ARCHIVE_BASE_URL + ARCHIVE_INGEST_TOKEN from .env) or from a
saved JSON via --export. What it fetches: one public, unauthenticated
oEmbed GET per YouTube / Vimeo video not already in the lookup cache,
interleaved across the two services (round-robin) and paced ~0.6s apart,
so neither host sees a burst. Nothing else touches the network; every
other host's discriminator is in the page's own address. Nothing is
written to the Archive.

Discriminator per host family (measured against the 2026-09-09 export):

    youtube   channel handle from oEmbed author_url   -> match=channel=@Handle
              (NOT in the URL; needs the WO that stores the channel on the
              page and passes it as a page_hint before these rules fire)
    vimeo     owner slug from oEmbed author_url       -> match=channel=<slug>
              (same plumbing needed; the /channels/<name>/ path form is
              also recorded and matches today)
    telvue    /player/<org token>/                    -> match=player/<token>
    clerkshq  /<Name>-<ST>                            -> match=<name>-<st>
    champds   /<tenant slug>/event/                   -> match=/<slug>/
    destiny   agenda_publish.cfm?...&id=<customer>    -> match=id=<customer>
    townhall  stream.php?...&location_id=<n>          -> match=location_id=<n>
    castus    /vod/<tenant>/                          -> match=vod/<tenant>/

Outputs (in --out, default reports/shared_host_study_<date>/):

    candidate_rules.csv     one row per (host, discriminator) that maps to
                            exactly ONE solidly-identified government and
                            is not already pinned -- tenant_overrides.csv
                            column order, ready to paste after review
    shared_discriminators.csv  a discriminator seen under >1 government
                            (a regional public-access channel, a vendor
                            channel) -- never to be pinned as-is
    already_pinned.csv      discriminators an existing row already covers
    would_fix.csv           weak-tier pages (unresolved/blank/unverified/
                            inferred/NULL) a candidate rule would key
    host_rules.csv          BONUS: single-government hosts (not shared)
                            that still have unresolved/blank/unverified
                            pages -- a plain host pin each (cablecast/
                            swagit tenants). Two guards, both from real
                            misses: a host with ONE solid page is pinned
                            only when the hostname names the government
                            (dcccd.new.swagit.com holds one Duncanville
                            page), and never when the hostname's own
                            state token disagrees with the government
                            (juneauak... held two pages filed as Juneau,
                            WI). Rejects land in unhandled_hosts.csv
                            with the reason.
    unhandled_hosts.csv     hosts serving >1 government with no
                            discriminator extractor here yet
    SUMMARY.md              the counts

Lookup cache: `reports/shared_host_lookups.csv` (video key -> channel,
title). Seeded from `reports/pin_worklist_youtube.csv`; a re-run costs no
network for anything already there. A video that never answers (deleted,
private) is cached as a miss so it is not re-fetched.

"Solid" means jurisdiction_confidence in {registry, pinned,
manual_override} with a national (non-`rtr:`) gov_id -- the same evidence
tiers `crud._tenant_dominant_gov_id()` trusts. One page is enough to
assign a discriminator (Ryan, 2026-09-09: the vast majority are 1:1).

Usage:
    python scripts/study_shared_host_discriminators.py                 # live export
    python scripts/study_shared_host_discriminators.py --export pages.json
    python scripts/study_shared_host_discriminators.py --no-network    # cache only
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import certifi

# Must precede `import aiohttp` -- see CLAUDE.md's fresh-venv SSL bullet.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
load_dotenv(REPO_ROOT / ".env")
load_dotenv(Path.home() / "Documents" / "rtr-deeplink" / ".env")

from app.utils.gov_registry import registry  # noqa: E402
from app.utils.jurisdiction_enrich import (  # noqa: E402
    _validated_subdomain_hint_with_state as subdomain_state_hint,
)

LOOKUP_CACHE = REPO_ROOT / "reports" / "shared_host_lookups.csv"
YOUTUBE_SEED = REPO_ROOT / "reports" / "pin_worklist_youtube.csv"
OVERRIDES = REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"

USER_AGENT = "Mozilla/5.0 (compatible; rtr-deeplink shared-host study)"
LOOKUP_DELAY_SECONDS = 0.6
PAGE_DELAY_SECONDS = 0.5

SOLID_TIERS = {"registry", "pinned", "manual_override"}
WEAK_TIERS = {"unresolved", "blank", "unverified", "inferred"}

YOUTUBE_HOSTS = {"youtu.be", "www.youtube.com", "youtube.com", "m.youtube.com"}
VIMEO_HOSTS = {"vimeo.com", "player.vimeo.com", "www.vimeo.com"}

# The one host each family's rule is written against. YouTube pages arrive
# under three real hosts (www.youtube.com 653 / youtu.be 232 / youtube.com
# 47 in the 2026-09-09 sheet) and nothing normalises them; the study emits
# ONE row per channel under the canonical host and leaves fan-out to the
# apply step (or to the plumbing WO teaching the matcher that the variants
# are one host). Same for Vimeo.
CANONICAL_HOST = {"youtube": "www.youtube.com", "vimeo": "vimeo.com"}

_YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|/live/|/embed/|/shorts/|[?&]v=)([A-Za-z0-9_-]{11})"
)
_VIMEO_ID_RE = re.compile(
    r"(?:vimeo\.com/(?:.*?/)?(?:video/|videos/)?)(\d{6,12})(?:[/?#]|$)"
)
_VIMEO_CHANNEL_PATH_RE = re.compile(r"^/channels/([^/]+)/\d{6,12}")
_TELVUE_TOKEN_RE = re.compile(r"/player/([A-Za-z0-9_\-]{16,})", re.I)
_CLERKBASE_SLUG_RE = re.compile(r"/(?:Content/)?([A-Za-z]+-[A-Za-z]{2})(?:[/?]|$)")
_CHAMPDS_SLUG_RE = re.compile(r"^/([a-z0-9\-]+)/event/", re.I)
_CASTUS_TENANT_RE = re.compile(r"^/vod/([^/]+)/", re.I)


def host_of(url: Optional[str]) -> str:
    return (urlparse(url or "").netloc or "").lower().split(":")[0]


def is_solid(page: dict) -> bool:
    gid = page.get("gov_id") or ""
    return (
        page.get("jurisdiction_confidence") in SOLID_TIERS
        and bool(gid)
        and not gid.startswith("rtr:")
    )


def is_weak(page: dict) -> bool:
    gid = page.get("gov_id") or ""
    tier = page.get("jurisdiction_confidence") or ""
    return (not gid) or gid.startswith("rtr:") or tier in WEAK_TIERS


# --------------------------------------------------------------------------
# Discriminator extraction: (family, lookup_key_or_None, match_or_None)
# --------------------------------------------------------------------------


def classify(page: dict) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Every shared-host discriminator this page carries, as
    (family, lookup_key, match) -- `match` straight from the address, or
    `lookup_key` for a video a network lookup turns into one.

    A page can carry TWO: its own host's discriminator (a ClerkBase site
    slug, a TelVue token) AND the channel of the YouTube/Vimeo video it
    embeds. Both are learned. The rule keyed on the page's own host is the
    one that fires for that page (Ryan's rule: the page's host wins); the
    channel rule only ever fires for a bare video paste, but this page is
    still evidence for it.
    """
    src = page.get("source_url_normalized") or ""
    vid = page.get("video_url") or ""
    src_host = host_of(src)
    out: List[Tuple[str, Optional[str], Optional[str]]] = []

    path = urlparse(src).path
    query = parse_qs(urlparse(src).query)
    if src_host == "videoplayer.telvue.com":
        m = _TELVUE_TOKEN_RE.search(src)
        if m:
            out.append(("telvue", None, f"player/{m.group(1)}"))
    elif src_host == "clerkshq.com":
        m = _CLERKBASE_SLUG_RE.search(path)
        if m:
            out.append(("clerkshq", None, m.group(1).lower()))
    elif src_host == "play.champds.com":
        m = _CHAMPDS_SLUG_RE.search(path)
        if m:
            out.append(("champds", None, f"/{m.group(1).lower()}/"))
    elif src_host == "public.destinyhosted.com":
        cid = (query.get("id") or [""])[0]
        if cid:
            out.append(("destiny", None, f"id={cid}"))
    elif src_host == "townhallstreams.com":
        loc = (query.get("location_id") or [""])[0]
        if loc:
            out.append(("townhall", None, f"location_id={loc}"))
    elif src_host == "cloud.castus.tv":
        m = _CASTUS_TENANT_RE.search(path)
        if m:
            out.append(("castus", None, f"vod/{m.group(1).lower()}/"))

    for url in (src, vid):
        h = host_of(url)
        if h in YOUTUBE_HOSTS or (url is src and page.get("platform") == "youtube"):
            m = _YOUTUBE_ID_RE.search(url)
            if m:
                out.append(("youtube", f"youtube:{m.group(1)}", None))
                break
    for url in (src, vid):
        if host_of(url) in VIMEO_HOSTS:
            m = _VIMEO_ID_RE.search(url)
            if m:
                out.append(("vimeo", f"vimeo:{m.group(1)}", None))
                break
    return out


FAMILY_HOST = {
    "youtube": "www.youtube.com",
    "vimeo": "vimeo.com",
    "telvue": "videoplayer.telvue.com",
    "clerkshq": "clerkshq.com",
    "champds": "play.champds.com",
    "destiny": "public.destinyhosted.com",
    "townhall": "townhallstreams.com",
    "castus": "cloud.castus.tv",
}
NEEDS_PLUMBING = {"youtube", "vimeo"}


# --------------------------------------------------------------------------
# Lookup cache + interleaved oEmbed fetch
# --------------------------------------------------------------------------


def load_cache() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if YOUTUBE_SEED.exists():
        with open(YOUTUBE_SEED, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("video_id"):
                    out[f"youtube:{row['video_id']}"] = {
                        "channel": row.get("channel") or "",
                        "channel_title": row.get("channel_title") or "",
                    }
    if LOOKUP_CACHE.exists():
        with open(LOOKUP_CACHE, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out[row["video_key"]] = {
                    "channel": row.get("channel") or "",
                    "channel_title": row.get("channel_title") or "",
                }
    return out


def save_cache(cache: Dict[str, dict]) -> None:
    LOOKUP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOOKUP_CACHE, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["video_key", "channel", "channel_title"])
        for key in sorted(cache):
            w.writerow([key, cache[key]["channel"], cache[key]["channel_title"]])


async def _oembed(session, family: str, video_id: str) -> Optional[dict]:
    if family == "youtube":
        url = "https://www.youtube.com/oembed"
        params = {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "format": "json",
        }
    else:
        url = "https://vimeo.com/api/oembed.json"
        params = {"url": f"https://vimeo.com/{video_id}"}
    try:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                return {"_status": resp.status}
            return await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None


async def fetch_lookups(
    keys: List[str],
    cache: Dict[str, dict],
    delay: float,
    backoff_delay: Optional[float] = None,
) -> Counter:
    """Round-robin across families so no single host sees a burst.

    `backoff_delay` (defaults to `delay`, i.e. no backoff): the wait used
    immediately after a miss/failure instead of `delay`. This script has
    no block-detection of its own -- a miss is as likely to be one dead
    video as the start of a block -- so the cheap, safe response to ANY
    miss is to slow down for the next request rather than wait for a
    run of misses to confirm a pattern. Drops back to `delay` the moment
    a lookup succeeds again.
    """
    backoff_delay = delay if backoff_delay is None else backoff_delay
    todo = [k for k in keys if k not in cache]
    stats: Counter = Counter()
    if not todo:
        return stats
    queues: Dict[str, List[str]] = defaultdict(list)
    for k in todo:
        queues[k.split(":", 1)[0]].append(k)
    order = sorted(queues)
    print(
        f"  {len(todo)} lookups to do: "
        + ", ".join(f"{f} {len(queues[f])}" for f in order)
    )
    done = 0
    last_was_miss = False
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        while any(queues.values()):
            for fam in order:
                if not queues[fam]:
                    continue
                key = queues[fam].pop(0)
                video_id = key.split(":", 1)[1]
                payload = await _oembed(session, fam, video_id)
                if payload and "_status" not in payload:
                    author_url = (payload.get("author_url") or "").rstrip("/")
                    handle = author_url.rsplit("/", 1)[-1] if author_url else ""
                    cache[key] = {
                        "channel": handle,
                        "channel_title": (payload.get("author_name") or "").strip(),
                    }
                    stats[f"{fam}_ok"] += 1
                    last_was_miss = False
                else:
                    # Deleted/private/blocked: cache the miss so it is never
                    # re-fetched; the status is kept for the summary only.
                    cache[key] = {"channel": "", "channel_title": ""}
                    stats[f"{fam}_miss_{(payload or {}).get('_status', 'err')}"] += 1
                    last_was_miss = True
                done += 1
                if done % 25 == 0:
                    save_cache(cache)
                print(
                    f"  [{done}/{len(todo)}] {key} {cache[key]['channel_title'][:40]}",
                    end="\r",
                )
                await asyncio.sleep(backoff_delay if last_was_miss else delay)
    save_cache(cache)
    print(" " * 78, end="\r")
    return stats


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


async def fetch_export_pages(base_url: str, token: str, limit: int = 500) -> List[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url.rstrip('/')}/internal/export/pages"
    pages: List[dict] = []
    after_id = 0
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                url,
                params={"after_id": after_id, "limit": limit},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    raise SystemExit(f"GET {url} -> HTTP {resp.status}")
                body = await resp.json()
            pages.extend(body.get("pages") or [])
            print(f"  fetched {len(pages)} pages", end="\r", flush=True)
            after_id = body.get("next_after_id")
            if after_id is None:
                break
            await asyncio.sleep(PAGE_DELAY_SECONDS)
    print(f"  fetched {len(pages)} pages      ")
    return pages


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def existing_pins() -> Dict[Tuple[str, str], dict]:
    out = {}
    with open(OVERRIDES, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[(row["tenant_host"].lower(), (row["match"] or "").lower())] = row
    return out


def write_csv(path: Path, header: List[str], rows: List[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--export", type=Path, help="saved /internal/export/pages JSON")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--no-network", action="store_true", help="use the lookup cache only"
    )
    ap.add_argument("--delay", type=float, default=LOOKUP_DELAY_SECONDS)
    ap.add_argument(
        "--backoff-delay",
        type=float,
        default=None,
        help="wait used right after a miss/failure instead of --delay "
        "(default: same as --delay, i.e. no backoff)",
    )
    args = ap.parse_args()

    out_dir = args.out or (
        REPO_ROOT / "reports" / f"shared_host_study_{date.today().isoformat()}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.export:
        pages = json.loads(args.export.read_text(encoding="utf-8"))
        if isinstance(pages, dict):
            pages = pages.get("pages") or []
    else:
        base_url = os.environ.get("ARCHIVE_BASE_URL")
        token = os.environ.get("ARCHIVE_INGEST_TOKEN")
        if not base_url or not token:
            raise SystemExit(
                "ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN must be set, or pass --export"
            )
        pages = asyncio.run(fetch_export_pages(base_url, token))
    print(f"{len(pages)} pages in export")

    # 1. classify every page
    classified: List[Tuple[dict, str, Optional[str], Optional[str]]] = []
    for p in pages:
        for c in classify(p):
            classified.append((p, *c))
    fam_counts = Counter(fam for _, fam, _, _ in classified)
    print("pages by shared-host family:", dict(fam_counts))

    # 2. network lookups for youtube/vimeo (solid AND weak pages -- weak ones
    #    are what the rules will fix, so their channel is needed to say so)
    cache = load_cache()
    keys = sorted({k for _, _, k, _ in classified if k})
    stats = Counter()
    if not args.no_network:
        stats = asyncio.run(fetch_lookups(keys, cache, args.delay, args.backoff_delay))
    else:
        print(
            f"  --no-network: {sum(1 for k in keys if k in cache)}/{len(keys)} keys cached"
        )

    # 3. resolve every page to (family, match)
    resolved: List[Tuple[dict, str, str, Optional[str]]] = []
    unlooked = Counter()
    for p, fam, key, match in classified:
        if match is None:
            hit = cache.get(key or "")
            if not hit or not hit["channel"]:
                unlooked[fam] += 1
                continue
            match = f"channel={hit['channel']}"
        resolved.append((p, fam, match, key))

    # 4. group by (family, match)
    govs_by_disc: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    pages_by_disc: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    title_by_disc: Dict[Tuple[str, str], str] = {}
    for p, fam, match, key in resolved:
        pages_by_disc[(fam, match)].append(p)
        if key and not title_by_disc.get((fam, match)):
            title_by_disc[(fam, match)] = (cache.get(key) or {}).get(
                "channel_title", ""
            )
        if is_solid(p):
            govs_by_disc[(fam, match)][p["gov_id"]] += 1

    govs = registry.governments()
    pins = existing_pins()
    today = date.today().isoformat()

    candidate_rows, shared_rows, pinned_rows, fix_rows = [], [], [], []
    for (fam, match), counter in sorted(govs_by_disc.items()):
        host = FAMILY_HOST[fam]
        plist = pages_by_disc[(fam, match)]
        title = title_by_disc.get((fam, match), "")
        if len(counter) > 1:
            shared_rows.append(
                [host, match, title, len(plist)]
                + [
                    f"{g} ({(govs.get(g).gov_name if govs.get(g) else '?')}) x{n}"
                    for g, n in counter.most_common()
                ]
            )
            continue
        gov_id, n_solid = next(iter(counter.items()))
        gov = govs.get(gov_id)
        gov_name = gov.gov_name if gov else ""
        pin_keys = [(host, match.lower())]
        if fam == "telvue":
            # 8 hand-written TelVue rows carry the bare token as `match`;
            # substring matching makes that and `player/<token>` one rule.
            pin_keys.append((host, match.lower().removeprefix("player/")))
        pin_hit = next((pins[k] for k in pin_keys if k in pins), None)
        if pin_hit:
            pinned_rows.append(
                [host, match, gov_id, gov_name, pin_hit["gov_id"], n_solid]
            )
            continue
        example = next((p["slug"] for p in plist if is_solid(p)), plist[0]["slug"])
        evidence = f"{n_solid} solidly-identified archive page(s), e.g. /m/{example}"
        if title:
            evidence += f'; owner title "{title}"'
        candidate_rows.append(
            [
                host,
                match,
                gov_id,
                "fallback",
                f"archive_study_{today}",
                evidence,
                gov_name,
                n_solid,
                fam in NEEDS_PLUMBING,
            ]
        )
        for p in plist:
            if is_weak(p):
                # Cheap plausibility flag for the review pass: a rule
                # learned from ONE archive page can be that page's own
                # misattribution (found live: a shared public-access
                # channel posting Half Moon Bay AND Pacifica meetings,
                # with only a Pacifica page solid in the archive). If the
                # proposed government's name is nowhere in the weak page's
                # title or slug, a human should look before the rule lands.
                hay = f"{p.get('title') or ''} {p.get('slug') or ''}".lower()
                stem = re.sub(
                    r"\b(city|county|town|village|borough|township|parish)\b",
                    "",
                    gov_name.lower(),
                ).strip()
                name_in_page = bool(stem) and stem.split()[0] in hay
                fix_rows.append(
                    [
                        p["id"],
                        p["slug"],
                        host,
                        match,
                        p.get("jurisdiction") or "",
                        p.get("gov_id") or "",
                        p.get("jurisdiction_confidence") or "",
                        gov_id,
                        gov_name,
                        n_solid,
                        "yes" if name_in_page else "REVIEW",
                    ]
                )

    # 5. discriminators seen only on weak pages (no solid page to learn from)
    weak_only = [
        (fam, match, len(plist))
        for (fam, match), plist in pages_by_disc.items()
        if (fam, match) not in govs_by_disc
    ]

    # 6. BONUS: single-government hosts with weak pages -> plain host pins
    by_host: Dict[str, List[dict]] = defaultdict(list)
    shared_family_hosts = set(YOUTUBE_HOSTS | VIMEO_HOSTS | set(FAMILY_HOST.values()))
    for p in pages:
        h = host_of(p.get("source_url_normalized"))
        if h and h not in shared_family_hosts:
            by_host[h].append(p)
    host_rows, unhandled_rows = [], []
    for h, plist in sorted(by_host.items()):
        solid = Counter(p["gov_id"] for p in plist if is_solid(p))
        # "Weak" here excludes `inferred`: an inferred page already carries
        # the tenant's own government (the consistency rung keyed it), so a
        # host whose only weak pages are inferred gains nothing from a pin
        # -- and pinning it would turn the rung's guarded answer into an
        # unguarded one (tests/test_gov_registry.py's consistency cases
        # use exactly such hosts).
        weak = [
            p
            for p in plist
            if is_weak(p) and (p.get("jurisdiction_confidence") or "") != "inferred"
        ]
        if len(solid) > 1:
            unhandled_rows.append(
                [h, len(solid), len(plist), len(weak)]
                + [f"{g} x{n}" for g, n in solid.most_common(4)]
            )
            continue
        if len(solid) == 1 and weak and (h, "") not in pins:
            gov_id = next(iter(solid))
            gov = govs.get(gov_id)
            gov_name = gov.gov_name if gov else ""
            # One solid page is enough for a DISCRIMINATOR rule (Ryan,
            # 2026-09-09) but not for a whole-host pin: found live,
            # `dcccd.new.swagit.com` (Dallas College) holds one solid
            # Duncanville page and would have been pinned to Duncanville.
            # A single-page host pin is written only when the hostname
            # itself names the government.
            stem = re.sub(
                r"\b(city|county|town|village|borough|township|parish)\b",
                "",
                gov_name.lower(),
            ).strip()
            stem = re.sub(r"[^a-z0-9]", "", stem.split()[0]) if stem else ""
            named = bool(stem) and stem in h.replace("-", "").replace("_", "")
            # The hostname's own state beats the archive's pages. Found by
            # tests/test_gov_registry.py::test_tenant_consistency_will_not_
            # cross_a_state_line: `juneauak.portal.civicclerk.com` holds two
            # registry-tier pages filed as Juneau, WI (a name collision the
            # place table cannot see), and a host pin built from them would
            # have cemented the wrong state for the City and Borough of
            # Juneau. `_validated_subdomain_hint_with_state()` reads the
            # state the label itself spells out ("juneauak" -> AK).
            hinted = subdomain_state_hint(h)
            hint_state = (hinted[1] or "").upper() if hinted else ""
            if hint_state and gov and (gov.state or "").upper() != hint_state:
                unhandled_rows.append(
                    [
                        h,
                        1,
                        len(plist),
                        len(weak),
                        f"{gov_id} x{solid[gov_id]} ({gov_name}, {gov.state}) but the hostname says {hint_state} -- not pinned, archive pages suspect",
                    ]
                )
                continue
            if solid[gov_id] < 2 and not named:
                unhandled_rows.append(
                    [
                        h,
                        1,
                        len(plist),
                        len(weak),
                        f"{gov_id} x1 (single solid page, hostname does not name it -- not pinned)",
                    ]
                )
                continue
            host_rows.append(
                [
                    h,
                    "",
                    gov_id,
                    "fallback",
                    f"archive_study_{today}",
                    f"{solid[gov_id]} solid page(s) all {gov_id}; {len(weak)} weak page(s) e.g. /m/{weak[0]['slug']}",
                    gov_name,
                    solid[gov_id],
                    len(weak),
                ]
            )

    write_csv(
        out_dir / "candidate_rules.csv",
        [
            "tenant_host",
            "match",
            "gov_id",
            "strength",
            "source",
            "evidence",
            "gov_name",
            "solid_pages",
            "needs_plumbing",
        ],
        candidate_rows,
    )
    write_csv(
        out_dir / "shared_discriminators.csv",
        ["tenant_host", "match", "owner_title", "pages", "governments..."],
        shared_rows,
    )
    write_csv(
        out_dir / "already_pinned.csv",
        [
            "tenant_host",
            "match",
            "study_gov_id",
            "study_gov_name",
            "existing_pin_gov_id",
            "solid_pages",
        ],
        pinned_rows,
    )
    write_csv(
        out_dir / "would_fix.csv",
        [
            "page_id",
            "slug",
            "tenant_host",
            "match",
            "current_jurisdiction",
            "current_gov_id",
            "current_tier",
            "proposed_gov_id",
            "proposed_gov_name",
            "rule_solid_pages",
            "proposed_name_in_page",
        ],
        fix_rows,
    )
    write_csv(
        out_dir / "weak_only_discriminators.csv",
        ["family", "match", "pages"],
        sorted(weak_only),
    )
    write_csv(
        out_dir / "host_rules.csv",
        [
            "tenant_host",
            "match",
            "gov_id",
            "strength",
            "source",
            "evidence",
            "gov_name",
            "solid_pages",
            "weak_pages",
        ],
        host_rows,
    )
    write_csv(
        out_dir / "unhandled_hosts.csv",
        ["tenant_host", "governments", "pages", "weak_pages", "top..."],
        sorted(unhandled_rows, key=lambda r: -r[3]),
    )

    disagree = sum(1 for r in pinned_rows if r[2] != r[4])
    lines = [
        f"# Shared-host discriminator study -- {today}",
        "",
        f"- pages in export: {len(pages)}",
        f"- pages on a shared-host family: {sum(fam_counts.values())} ({dict(fam_counts)})",
        f"- oEmbed lookups this run: {dict(stats) or 'none'}",
        f"- pages whose video never answered (no channel): {dict(unlooked) or 'none'}",
        "",
        f"- **candidate rules (1:1, not yet pinned): {len(candidate_rows)}**"
        f" -- of which need the channel plumbing before they fire: {sum(1 for r in candidate_rows if r[8])}",
        f"- weak-tier pages those rules would key: {len(fix_rows)}"
        f" (proposed government named in the page: {sum(1 for r in fix_rows if r[-1] == 'yes')}; REVIEW: {sum(1 for r in fix_rows if r[-1] == 'REVIEW')})",
        f"- shared discriminators (>1 government, NOT pinned): {len(shared_rows)}",
        f"- already pinned: {len(pinned_rows)} (existing pin disagrees with the archive on {disagree})",
        f"- discriminators seen only on weak pages (nothing to learn from yet): {len(weak_only)}",
        f"- BONUS single-government hosts with weak pages (plain host pins): {len(host_rows)}"
        f" covering {sum(r[8] for r in host_rows)} weak pages",
        f"- multi-government hosts with no extractor here: {len(unhandled_rows)}",
        "",
        "## Candidate rules by family",
    ]
    for fam, n in sorted(
        Counter(FAMILY_HOST_INV[r[0]] for r in candidate_rows).items()
    ):
        fixes = sum(1 for r in fix_rows if FAMILY_HOST_INV[r[2]] == fam)
        lines.append(f"- {fam}: {n} rules, would key {fixes} weak pages")
    (out_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {out_dir}")


FAMILY_HOST_INV = {v: k for k, v in FAMILY_HOST.items()}

if __name__ == "__main__":
    main()
