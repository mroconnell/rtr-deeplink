"""Orchestrates Steps 2-4 for one leads row: makes the real YouTube call(s)
(as few as possible -- one per row in the common case, a second only when
a single_video row needs its channel walked per Ryan's rule), calls judge.py
for the decision, and returns one Verdict. No network call happens inside
judge.py itself -- this is the only place that touches YouTube.
"""

import json
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
    source_wo = row.get("source_wo", "")

    gov = government_for_id(gid) if gid else None
    gov_kind = gov.gov_type if gov else None

    linked_from_gov_site = source_wo in HOMEPAGE_WALK_SOURCES

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
