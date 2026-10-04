"""Orchestrates Steps 2-4 for one leads row: makes the real YouTube call(s)
(as few as possible -- one per row in the common case, a second only when
a single_video row needs its channel walked per Ryan's rule), calls judge.py
for the decision, and returns one Verdict. No network call happens inside
judge.py itself -- this is the only place that touches YouTube.
"""

import csv
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.youtube_leads_judge import assess_identity, pick_best_meeting  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402

logger = logging.getLogger(__name__)

MIN_CANDIDATES_BEFORE_REJECT = 3

HOMEPAGE_WALK_SOURCES = {
    "WO-281",
    "WO-282",
    "WO-283",
    "WO-292",
    "WO-320",
    "WO-321",
    "WO-322",
    "WO-323",
    "WO-324",
    "WO-325",
    "WO-331",
    "WO-337",
    "WO-338",
    "WO-353",
    "WO-361",
    "WO-364",
    "WO-911",
    "WO-913",
}  # homepage-hop / passive-discovery families -- found BY walking the
# government's own site, so "linked from the government's own website"
# is already true by construction for these, per each script's own
# docstring (fetch_and_score()/find_hop_links() etc. all start from the
# government's own homepage). meeting-finder-2026-09-24-run3 is NOT in
# this set -- unconfirmed provenance, so identity can only reach Medium
# from name-match alone unless the video/channel's own page confirms it.


FINDMEETING_PREFIX = "findmeeting_"
HAND_REVIEW_PREFIX = "hand_review_"
# The `run` values in reports/drip_handoff_*/leads.csv (run_govs_01..03,
# group4_*, findmeeting_*). A handoff row has no `source_wo`; a run with one
# of these prefixes means the same thing as a `findmeeting_*` source: the
# address was found on the government's own website. `hand_review_*` is not
# here: those rows are Ryan's hand decisions, handled by is_person_confirmed.
HANDOFF_RUN_PREFIXES = (FINDMEETING_PREFIX, "run_govs_", "group4_")
LEADS_CSV_ENV = "RTR_LEADS_CSV"
DEFAULT_LEADS_CSV = (
    Path.home()
    / "Documents"
    / "rtr-business"
    / "research"
    / "youtube_channel_leads.csv"
)
LEADS_CSV = DEFAULT_LEADS_CSV  # kept for older imports; use leads_csv_path()


def leads_csv_path():
    """The research leads file: the RTR_LEADS_CSV environment variable when
    set, else ~/Documents/rtr-business/research/youtube_channel_leads.csv."""
    env = (os.environ.get(LEADS_CSV_ENV) or "").strip()
    return Path(env).expanduser() if env else DEFAULT_LEADS_CSV


_YT_ID_RES = (
    re.compile(r"youtu\.be/([\w-]{6,})", re.I),
    re.compile(r"[?&]v=([\w-]{6,})", re.I),
    re.compile(r"/(?:embed|v|shorts)/([\w-]{6,})", re.I),
    re.compile(r"/channel/([\w-]+)", re.I),
    re.compile(r"/@([^/?#]+)", re.I),
    re.compile(r"/(?:user|c)/([^/?#]+)", re.I),
)


def address_key(url):
    """One comparable key per YouTube address (video id, channel id or
    handle, lower-cased). Falls back to the lower-cased url minus its
    scheme, so a Vimeo address still compares with itself."""
    u = (url or "").strip()
    for rx in _YT_ID_RES:
        m = rx.search(u)
        if m:
            return m.group(1).lower()
    return re.sub(r"^https?://(www\.)?", "", u.lower()).rstrip("/")


_STATE_NAMES = (
    "AL alabama,AK alaska,AZ arizona,AR arkansas,CA california,CO colorado,"
    "CT connecticut,DE delaware,DC district of columbia,FL florida,GA georgia,"
    "HI hawaii,ID idaho,IL illinois,IN indiana,IA iowa,KS kansas,KY kentucky,"
    "LA louisiana,ME maine,MD maryland,MA massachusetts,MI michigan,"
    "MN minnesota,MS mississippi,MO missouri,MT montana,NE nebraska,NV nevada,"
    "NH new hampshire,NJ new jersey,NM new mexico,NY new york,"
    "NC north carolina,ND north dakota,OH ohio,OK oklahoma,OR oregon,"
    "PA pennsylvania,RI rhode island,SC south carolina,SD south dakota,"
    "TN tennessee,TX texas,UT utah,VT vermont,VA virginia,WA washington,"
    "WV west virginia,WI wisconsin,WY wyoming"
)
_STATE_BY_CODE = {
    x[:2].lower(): x[3:] for x in _STATE_NAMES.split(",")
}  # "ny" -> "new york"

# Template embeds Ryan named on 2026-10-03, always shared. The leads file
# holds each address once, so it cannot show these on its own. The Wix
# entries are the Wix addresses seen in that file; confirm the list.
KNOWN_TEMPLATE_ADDRESSES = {
    "bqlup7guutg",
    "dewi11channel",
    "wix",
    "wixstudio",
    "wixmypage",
}

_URL_RE = re.compile(r"https?://[^\s|;,]+")
_SHARED_ADDRESSES_CACHE = {}


def _norm_state(st):
    st = (st or "").strip().lower()
    return _STATE_BY_CODE.get(st, st)


def _handoff_csvs():
    return sorted((REPO / "reports").glob("drip_handoff_*/leads.csv"))


def _load_guard(path=None, extra_paths=None):
    """Read the files once per run per path. Returns a dict:
    shared (addresses in two or more states, plus KNOWN_TEMPLATE_ADDRESSES),
    runs (address key -> set of handoff `run` values), source (which files
    were read). Returns None when nothing could be read."""
    path = Path(path) if path else leads_csv_path()
    extra = _handoff_csvs() if extra_paths is None else list(extra_paths)
    key = (path, tuple(extra))
    if key in _SHARED_ADDRESSES_CACHE:
        return _SHARED_ADDRESSES_CACHE[key]
    states = {}
    runs = {}

    def note(url, st, run=None):
        k = address_key(url) if url else None
        if not k:
            return
        st = _norm_state(st)
        if st:
            states.setdefault(k, set()).add(st)
        if run:
            runs.setdefault(k, set()).add(run)

    research_ok = True
    try:
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(ln for ln in f if not ln.startswith("#")):
                note(r.get("channel_url"), r.get("state"))
    except OSError:
        research_ok = False
    handoff_read = 0
    for ep in extra:
        try:
            with Path(ep).open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    run = (r.get("run") or "").strip()
                    note(r.get("lead_url"), r.get("state"), run)
                    for u in _URL_RE.findall(r.get("all_youtube_addresses_seen") or ""):
                        note(u, r.get("state"), run)
            handoff_read += 1
        except OSError:
            continue
    if not research_ok and not handoff_read:
        result = None
        logger.warning(
            "leads guard: no leads file readable (%s) and no handoff leads.csv; "
            "no Find Meeting credit will be given",
            path,
        )
    else:
        shared = {k for k, v in states.items() if len(v) >= 2}
        shared |= KNOWN_TEMPLATE_ADDRESSES
        if research_ok:
            source = f"research leads file {path} + {handoff_read} handoff leads.csv"
        else:
            source = (
                f"{handoff_read} handoff leads.csv only (research file {path} "
                "not readable)"
            )
        logger.info("leads guard source: %s", source)
        result = {"shared": shared, "runs": runs, "source": source}
    _SHARED_ADDRESSES_CACHE[key] = result
    return result


def shared_addresses(path=None, extra_paths=None):
    """Addresses that appear for governments in two or more different
    states. Those are website-template embeds, not a government's own
    channel. Sources: the research leads file (channel_url + state; path
    from RTR_LEADS_CSV or the default), the drip handoff files in reports/
    (lead_url and every address in all_youtube_addresses_seen, with the
    row's state), and KNOWN_TEMPLATE_ADDRESSES. When the research file is
    missing the handoff files alone are used. Read once per run per path.
    Returns None only when neither the research file nor any handoff file
    can be read; callers then give no credit. Limit: it only sees addresses
    in those files."""
    g = _load_guard(path, extra_paths)
    return None if g is None else g["shared"]


def is_linked_from_gov_site(source_wo, url, leads_path=None, extra_paths=None):
    """True when the lead's source means "found by walking the
    government's own website". WO families: exact list. Find Meeting
    (`findmeeting_*`) and handoff runs (`run_govs_*`, `group4_*`): yes,
    unless the address is a template embed seen for governments in
    different states (or no file at all can be read, which fails closed).
    A blank source (a handoff row copied into the queue without its source)
    is looked up in the handoff files by address: a run with one of those
    prefixes counts the same way."""
    source_wo = (source_wo or "").strip()
    if source_wo in HOMEPAGE_WALK_SOURCES:
        return True
    if source_wo.startswith(HANDOFF_RUN_PREFIXES):
        g = _load_guard(leads_path, extra_paths)
        return g is not None and address_key(url) not in g["shared"]
    if not source_wo:
        g = _load_guard(leads_path, extra_paths)
        if g is None:
            return False
        k = address_key(url)
        if k in g["shared"]:
            return False
        return any(r.startswith(HANDOFF_RUN_PREFIXES) for r in g["runs"].get(k, ()))
    return False


def is_person_confirmed(row):
    """A `hand_review_*` row Ryan marked verified=true: a person already
    confirmed the identity."""
    return (row.get("source_wo") or "").startswith(HAND_REVIEW_PREFIX) and (
        str(row.get("verified") or "").strip().lower() == "true"
    )


@dataclass
class Verdict:
    channel_url: str
    gov_id: str
    government: str
    kind: str
    verdict: str  # pass | wrong-government | off-mission | no-meetings-on-channel
    # | dead | embed-restricted | needs-human
    reason: str
    picked_video_url: Optional[str] = None
    picked_title: Optional[str] = None
    identity_tier: Optional[str] = None
    n_candidates_seen: int = 0


def channel_videos_url(url):
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if re.search(r"/(videos|streams|live)$", path):
        return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return urlunsplit((parts.scheme, parts.netloc, path + "/videos", "", ""))


def yt_dump(url, playlist_end=12):
    try:
        out = subprocess.run(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                "-J",
                "--flat-playlist",
                "--playlist-end",
                str(playlist_end),
                "--no-warnings",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # Only stderr, never stdout -- a real ~500KB channel/video JSON dump
        # can easily contain the bare digits "429" or similar somewhere in a
        # URL/signature/timestamp field, a false positive confirmed live
        # (Martin County, Bjns_TgbkME) that would have wrongly halted the
        # whole run. yt-dlp writes its own real errors to stderr only.
        low = (out.stderr or "").lower()
        if (
            any(
                s in low
                for s in (
                    "sign in to confirm you",
                    "429",
                    "too many requests",
                    "http error 429",
                )
            )
            and "sign in to confirm your age" not in low
        ):
            return None, "BLOCK"
        if "sign in to confirm your age" in low:
            return None, "AGE_GATED"
        if not (out.stdout or "").strip():
            err = (out.stderr or "").strip()
            if any(
                s in err.lower()
                for s in (
                    "private video",
                    "video unavailable",
                    "this channel does not exist",
                    "account terminated",
                    "account suspended",
                    "content isn't available",
                )
            ):
                return None, "DEAD"
            return None, err[:300] or "empty response"
        return json.loads(out.stdout), None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, str(e)


def entries_from_dump(data, cap=8):
    out = []
    for e in (data.get("entries") or [])[:cap]:
        if e is None:
            continue
        out.append(
            (
                e.get("id"),
                e.get("title") or "",
                e.get("duration"),
                not bool(
                    e.get("availability") == "needs_auth"
                    or e.get("live_status") == "is_upcoming"
                ),
            )
        )
    return out


def process_row(row) -> Verdict:
    gid = (row.get("gov_id") or "").strip()
    gov_name = row.get("government") or gid
    gov_state = row.get("state") or ""
    kind = row.get("kind")
    url = row["channel_url"]
    source_wo = row.get("source_wo") or row.get("run") or ""

    gov = government_for_id(gid) if gid else None
    gov_kind = gov.gov_type if gov else None

    linked_from_gov_site = is_linked_from_gov_site(source_wo, url)
    confirmed_by_person = is_person_confirmed(row)

    def base(v, reason, **kw):
        return Verdict(url, gid, gov_name, kind, v, reason, **kw)

    if kind == "single_video":
        data, err = yt_dump(url, playlist_end=1)
        if err == "BLOCK":
            return base(
                "needs-human",
                "YouTube block signature seen -- stop and let a person/later run retry",
            )
        if err == "DEAD":
            return base("dead", f"video unavailable: {url}")
        if data is None:
            return base("needs-human", f"could not fetch: {err}")
        title = data.get("title") or ""
        channel_title = data.get("channel") or data.get("uploader") or ""
        channel_id = data.get("channel_id") or data.get("uploader_id")
        idv = assess_identity(
            channel_title=channel_title,
            channel_description=data.get("description"),
            gov_name=gov_name,
            gov_state=gov_state,
            gov_kind=gov_kind,
            linked_from_gov_site=linked_from_gov_site,
            kind=kind,
            confirmed_by_person=confirmed_by_person,
        )
        if idv.tier == "wrong-government":
            return base("wrong-government", idv.reason, identity_tier=idv.tier)
        best = pick_best_meeting(
            [(data.get("id"), title, data.get("duration"), True)], gov_kind
        )
        if best:
            vid, t, cv = best
            return base(
                "pass",
                f"identity {idv.tier}: {idv.reason}; {cv.reason}",
                picked_video_url=url,
                picked_title=t,
                identity_tier=idv.tier,
                n_candidates_seen=1,
            )
        # not a meeting on its own -- walk the channel per Ryan's rule
        if not channel_id and not channel_title:
            return base(
                "off-mission",
                "single video is not a meeting and has no channel to walk",
                n_candidates_seen=1,
            )
        chan_url = (
            f"https://www.youtube.com/channel/{channel_id}/videos"
            if channel_id
            else None
        )
        if chan_url is None:
            return base(
                "needs-human",
                "not a meeting on its own; channel id unavailable to walk further",
                n_candidates_seen=1,
            )
        return _walk_channel(
            chan_url,
            gid,
            gov_name,
            gov_state,
            gov_kind,
            kind,
            url,
            linked_from_gov_site,
            base,
            confirmed_by_person=confirmed_by_person,
            seed_title=title,
            seed_channel_title=channel_title,
        )

    # channel or playlist
    real_url = channel_videos_url(url) if kind == "channel" else url
    return _walk_channel(
        real_url,
        gid,
        gov_name,
        gov_state,
        gov_kind,
        kind,
        url,
        linked_from_gov_site,
        base,
        confirmed_by_person=confirmed_by_person,
    )


def _walk_channel(
    chan_url,
    gid,
    gov_name,
    gov_state,
    gov_kind,
    kind,
    orig_url,
    linked_from_gov_site,
    base,
    seed_title=None,
    seed_channel_title=None,
    confirmed_by_person=False,
):
    data, err = yt_dump(chan_url, playlist_end=MIN_CANDIDATES_BEFORE_REJECT + 5)
    if err == "BLOCK":
        return base(
            "needs-human",
            "YouTube block signature seen -- stop and let a person/later run retry",
        )
    if err == "AGE_GATED":
        return base(
            "embed-restricted", "age-gated, no login available to check further"
        )
    if err == "DEAD":
        return base("dead", f"channel unavailable: {chan_url}")
    if data is None:
        return base("needs-human", f"could not fetch channel: {err}")

    channel_title = (
        data.get("channel")
        or data.get("uploader")
        or data.get("title")
        or seed_channel_title
        or ""
    )
    idv = assess_identity(
        channel_title=channel_title,
        channel_description=data.get("description"),
        gov_name=gov_name,
        gov_state=gov_state,
        gov_kind=gov_kind,
        linked_from_gov_site=linked_from_gov_site,
        kind=kind,
        confirmed_by_person=confirmed_by_person,
    )
    if idv.tier == "wrong-government":
        return base("wrong-government", idv.reason, identity_tier=idv.tier)
    if idv.tier == "needs-human":
        return base("needs-human", idv.reason, identity_tier=idv.tier)

    entries = entries_from_dump(data)
    if not entries:
        return base(
            "no-meetings-on-channel",
            "channel has no listable videos",
            identity_tier=idv.tier,
        )

    best = pick_best_meeting(entries, gov_kind)
    if best:
        vid, t, cv = best
        return base(
            "pass",
            f"identity {idv.tier}: {idv.reason}; {cv.reason}",
            picked_video_url=f"https://www.youtube.com/watch?v={vid}",
            picked_title=t,
            identity_tier=idv.tier,
            n_candidates_seen=len(entries),
        )

    if len(entries) < MIN_CANDIDATES_BEFORE_REJECT:
        return base(
            "needs-human",
            f"only {len(entries)} video(s) visible, fewer than the 3 required before rejecting",
            identity_tier=idv.tier,
            n_candidates_seen=len(entries),
        )

    verdict = (
        "off-mission" if idv.tier in ("strong", "medium") else "no-meetings-on-channel"
    )
    return base(
        verdict,
        f"{len(entries)} videos checked, none is a real meeting (identity {idv.tier})",
        identity_tier=idv.tier,
        n_candidates_seen=len(entries),
    )
