"""Resolve-and-route stage3/stage4 playbook leads (2026-09-29). See
rtr-business research/slug_learning_2026-09-27/funnel_audit/
playbook_2026-09-29/stage34/README.md for the job brief. Adapted from
resolve_951.py (same throttle, same shared-station guard, same §398i
routing). Resumable: progress is checkpointed to state.json.

Input: stage4_video.csv (689 leads, meeting_url already populated) plus
the 40 stage3 cablecast_leftovers rows whose own evidence already says
"with video 0" (a confirmed no-video outcome, handled separately, no
resolver needed -- see write_stage3_no_video.py).

Run: .venv/bin/python scripts/resolve_stage34.py
"""
import asyncio, csv, json, os, sys, time, datetime
from pathlib import Path
from urllib.parse import urlparse, quote

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BIZ = Path("/Users/mroconnell/Documents/rtr-business/.claude/worktrees/agitated-lamarr-009d82")
OUT = BIZ / "research/slug_learning_2026-09-27/funnel_audit/playbook_2026-09-29/stage34"
OUT.mkdir(parents=True, exist_ok=True)
INPUT_CSV = BIZ / "research/slug_learning_2026-09-27/funnel_audit/playbook_2026-09-29/stage4_video.csv"
REGISTRY_CSV = BIZ / "research/jurisdiction_coverage.csv"
YT_LEADS_CSV = BIZ / "research/youtube_channel_leads.csv"

STATE_PATH = OUT / "state.json"
LOG = OUT / "requests.log"
STAMPS = OUT / ".stamps"
STAMPS.mkdir(exist_ok=True)
TELVUE_COUNT_PATH = OUT / "telvue_key_counts.json"
KALAMAZOO_KEY = "2bm0gzQWeVRzdCgvjXziXKwO3icSKh05"
TELVUE_CAP = 5
TIKILIVE_HOST = "civplus.tikiliveapi.com"
TIKILIVE_GAP = 4.6
DEFAULT_GAP = 3.0
UA = "Mozilla/5.0 (compatible; RTR-research/1.0)"
CALLER = "resolve_stage34_2026-09-29"
STALE_CUTOFF = datetime.date(2026, 9, 29) - datetime.timedelta(days=365 * 2)


def _log(status, url):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{status}\t{url}\n")


def _stamp_path(key):
    return STAMPS / (key.replace(":", "_").replace("/", "_")[:180])


def _wait_and_stamp(key, gap):
    p = _stamp_path(key)
    try:
        last = float(p.read_text())
    except Exception:
        last = 0
    w = gap - (time.time() - last)
    if w > 0:
        time.sleep(w)
    p.write_text(str(time.time()))


def _telvue_counts():
    if TELVUE_COUNT_PATH.exists():
        return json.loads(TELVUE_COUNT_PATH.read_text())
    return {}


def _telvue_bump(key):
    c = _telvue_counts()
    c[key] = c.get(key, 0) + 1
    TELVUE_COUNT_PATH.write_text(json.dumps(c))
    return c[key]


TELVUE_NON_KEY_SEGMENTS = {"media", "playlists", "stream", "videos", "api"}


def telvue_key_from_url(u):
    try:
        parts = urlparse(u).path.split("/")
        i = parts.index("player")
        key = parts[i + 1]
        if key in TELVUE_NON_KEY_SEGMENTS:
            return None
        return key
    except Exception:
        return None


CURRENT_TELVUE_KEY = [None]


class TelvueCapReached(Exception):
    pass


def setup_throttle():
    import aiohttp

    orig = aiohttp.ClientSession._request

    async def throttled(self, method, url, *a, **k):
        host = urlparse(str(url)).netloc
        is_archive = "redtaperecordings" in host or "onrender" in host
        if host == TIKILIVE_HOST:
            gap = TIKILIVE_GAP
        else:
            gap = DEFAULT_GAP
        if host.endswith("telvue.com"):
            key = telvue_key_from_url(str(url)) or CURRENT_TELVUE_KEY[0]
            if key == KALAMAZOO_KEY:
                raise TelvueCapReached("Kalamazoo's key is never fetched")
            if key:
                cur = _telvue_counts().get(key, 0)
                if cur >= TELVUE_CAP:
                    raise TelvueCapReached(f"telvue key {key[:8]} cap ({TELVUE_CAP}) reached")
                _telvue_bump(key)
        if not host:
            raise RuntimeError(f"empty host for request url={url!r} -- check ARCHIVE_BASE_URL/env")
        if not is_archive:
            _wait_and_stamp(host, gap)
        r = await orig(self, method, url, *a, **k)
        _log(r.status, f"{method} {url}")
        return r

    aiohttp.ClientSession._request = throttled
    return aiohttp


def _setup():
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)
    from dotenv import load_dotenv

    load_dotenv(os.path.expanduser("~/Documents/rtr-deeplink/.env"))
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    aiohttp = setup_throttle()
    sys.path.insert(0, str(REPO / "scripts"))
    import youtube_fetch_guard

    youtube_fetch_guard.install()
    return aiohttp


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"govs": {}, "jur_cache": {}, "hub_cache": {}, "yt_leads_written": [], "queue_written": []}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=1, default=str))


def load_rows():
    rows = []
    with open(INPUT_CSV) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def load_registry():
    by_id = {}
    if REGISTRY_CSV.exists():
        with open(REGISTRY_CSV) as f:
            for row in csv.DictReader(f):
                gid = (row.get("gov_id") or "").strip()
                if gid:
                    by_id[gid] = row
    return by_id


def load_queue_govs():
    p = REPO / "scripts/tier3_auto_transcription_queue.txt"
    govs = set()
    if p.exists():
        for line in p.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2].strip():
                govs.add(parts[2].strip())
    return govs


def group_by_gov(rows, registry):
    groups = {}
    tbd = []
    for r in rows:
        gid = (r.get("gov_id") or "").strip()
        if not gid or ";" in gid:
            tbd.append(r)
            continue
        groups.setdefault(gid, []).append(r)
    return groups, tbd


def build_host_gov_map(rows):
    m = {}
    for r in rows:
        gid = (r.get("gov_id") or "").strip()
        u = (r.get("meeting_url") or "").strip()
        if not gid or ";" in gid or not u:
            continue
        h = urlparse(u).netloc
        m.setdefault(h, set()).add(gid)
    return m


SHARED_HOST_DENYLIST_SUBSTR = ("communitymedia.net",)

NOT_A_MEETING_KEYWORDS = (
    "concert", "festival", "parade", "holiday special", "choir", "school play",
    "talent show", "fun run", "fireworks", "tree lighting", "market days",
    "variety show", "cooking show", "art show", "car show",
)

_PLACE_SUFFIXES = (
    " city", " town", " township", " charter township", " village", " borough",
    " county", " cousub", " csd", " cd", " district", " school district",
    " authority",
)


def _place_core(name):
    n = (name or "").lower().split(",")[0].strip()
    for suf in _PLACE_SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)].strip()
    return n


def is_shared_tenant(host, telvue_key, host_gov_map):
    if telvue_key:
        import app.utils.tenant_key as tk

        if (host, telvue_key) in tk.MULTI_GOVERNMENT_TENANTS:
            return True
    if any(s in host for s in SHARED_HOST_DENYLIST_SUBSTR):
        return True
    return len(host_gov_map.get(host, ())) > 1


def title_matches_government(title, gov_name):
    t = (title or "").lower()
    if not t:
        return False, "no title to check"
    for kw in NOT_A_MEETING_KEYWORDS:
        if kw in t:
            return False, f"title looks like a show/event, not a meeting ({kw!r})"
    core = _place_core(gov_name)
    if not core:
        return False, "no government name to match against"
    if core not in t:
        return False, f"government name {core!r} not found in title {title!r}"
    return True, "title contains the government's place name"


async def archive_get(aiohttp_mod, session, path, cache_key, state):
    url = f"https://redtaperecordings.com{path}"
    async with session.get(url, headers={"User-Agent": UA}, timeout=30) as resp:
        st = resp.status
        try:
            body = await resp.text()
        except Exception:
            body = ""
        return st, body


async def check_coverage(session, gov_name, state):
    if not gov_name or gov_name == "unknown":
        return False, "no government name to check", None
    ck = gov_name.lower()
    if ck in state["jur_cache"]:
        matches = state["jur_cache"][ck]
    else:
        url = f"https://redtaperecordings.com/api/jurisdictions?q={quote(gov_name)}"
        async with session.get(url, headers={"User-Agent": UA}, timeout=30) as resp:
            st = resp.status
            body = await resp.text()
        _log(st, url)
        try:
            matches = json.loads(body).get("matches", []) if st == 200 else []
        except Exception:
            matches = []
        state["jur_cache"][ck] = matches
        save_state(state)
    if not matches:
        return False, "no hub found by name", None
    exact = [m for m in matches if m.get("label", "").split(",")[0].strip().lower() == gov_name.split(",")[0].strip().lower()]
    m = exact[0] if exact else matches[0]
    link = m.get("link")
    if not link:
        return False, "match had no link", None
    if link in state["hub_cache"]:
        newest = state["hub_cache"][link]
    else:
        url = f"https://redtaperecordings.com{link}"
        async with session.get(url, headers={"User-Agent": UA}, timeout=30) as resp:
            st = resp.status
            body = await resp.text()
        _log(st, url)
        import re

        dates = re.findall(r"20\d\d-\d\d-\d\d", body)
        newest = max(dates) if dates else None
        state["hub_cache"][link] = newest
        save_state(state)
    if not newest:
        return False, f"hub {link} exists but no dated page found", None
    y, mo, d = (int(x) for x in newest.split("-"))
    newest_date = datetime.date(y, mo, d)
    if newest_date >= STALE_CUTOFF:
        return True, f"covered, newest page {newest}", newest
    return False, f"stale coverage, newest page {newest} (>2y old)", newest


def is_youtube(u):
    h = urlparse(u).netloc
    return "youtube.com" in h or "youtu.be" in h


async def resolve_one(u):
    from app.platforms.base import detect_platform, get_finder

    plat = detect_platform(u)
    finder = get_finder(plat)
    prev = CURRENT_TELVUE_KEY[0]
    CURRENT_TELVUE_KEY[0] = telvue_key_from_url(u)
    try:
        r = await finder.resolve(u)
    finally:
        CURRENT_TELVUE_KEY[0] = prev
    return plat, r


async def probe_one(u, video_url=None, platform=None):
    from app.platforms.queue_probe import probe_queue_entry

    prev = CURRENT_TELVUE_KEY[0]
    CURRENT_TELVUE_KEY[0] = telvue_key_from_url(u)
    try:
        return await probe_queue_entry(u, video_url=video_url, source_page_url=None, platform=platform)
    finally:
        CURRENT_TELVUE_KEY[0] = prev


async def ingest_one(aiohttp_mod, session, u, gov_id, resolved_payload):
    import bulk_ingest
    from app.utils.url_normalize import normalize_url

    payload = dict(resolved_payload)
    payload["gov_id"] = gov_id
    resp = await bulk_ingest._ingest(session, payload, normalize_url(u), caller=CALLER)
    return resp


def append_yt_lead(gov_id, gov_name, state_abbr, channel_or_video_url, note):
    key = f"{gov_id}|{channel_or_video_url}"
    with open(YT_LEADS_CSV, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([channel_or_video_url, gov_id, gov_name, state_abbr, CALLER, "single_video", "false", note])
    return key


RESULTS_FIELDS = [
    "stage", "gov_id", "gov_name", "bucket", "reason", "meeting_url", "platform",
    "tier", "duration_seconds", "archive_slug",
]


def append_result(row):
    new = not (OUT / "results.csv").exists()
    with open(OUT / "results.csv", "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULTS_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


async def handle_gov(aiohttp_mod, session, gid, rows, registry, queue_govs, state, host_gov_map, stage):
    if gid in state["govs"]:
        return
    reg = registry.get(gid)
    gov_name = (rows[0].get("gov_name") or "").strip()
    if (not gov_name or gov_name == "unknown") and reg:
        gov_name = reg.get("city_name", "")
    st_abbr = (reg.get("state_or_province") if reg else "") or ""

    if gid in queue_govs:
        row = dict(stage=stage, gov_id=gid, gov_name=gov_name, bucket="skipped: covered",
                    reason="already has a line in tier3_auto_transcription_queue.txt",
                    meeting_url="", platform="", tier="", duration_seconds="", archive_slug="")
        append_result(row); state["govs"][gid] = "skipped_queued"; save_state(state); return

    covered, reason, newest = await check_coverage(session, gov_name, state)
    if covered:
        row = dict(stage=stage, gov_id=gid, gov_name=gov_name, bucket="skipped: covered", reason=reason,
                    meeting_url="", platform="", tier="", duration_seconds="", archive_slug="")
        append_result(row); state["govs"][gid] = "skipped_covered"; save_state(state); return

    is_new_id = reg is None

    tier1_done = False
    yt_candidate = None
    tier3_candidates = []
    fail_reasons = []
    for r in rows:
        u = r["meeting_url"].strip()
        if not u:
            continue
        if is_youtube(u):
            if yt_candidate is None:
                yt_candidate = u
            continue
        try:
            plat, res = await resolve_one(u)
        except TelvueCapReached as e:
            fail_reasons.append(f"{u}: {e}")
            continue
        except Exception as e:
            fail_reasons.append(f"{u}: resolve error: {e!r}")
            continue
        segs = getattr(res, "segments", None) or []
        if segs:
            host = urlparse(u).netloc
            tkey = telvue_key_from_url(u) if host.endswith("telvue.com") else None
            if is_shared_tenant(host, tkey, host_gov_map):
                ok, why = title_matches_government(getattr(res, "title", None), gov_name)
                if not ok:
                    fail_reasons.append(
                        f"{u}: SHARED HOST MISMATCH ({host}{'/' + tkey[:8] if tkey else ''}): "
                        f"{why} -- title={getattr(res, 'title', None)!r} -- not ingested, needs a human check"
                    )
                    continue
            payload = res.model_dump(mode="json")
            try:
                resp = await ingest_one(aiohttp_mod, session, u, gid, payload)
                slug = (resp or {}).get("slug", "")
                row = dict(stage=stage, gov_id=gid, gov_name=gov_name, bucket="ingested",
                            reason=f"tier 1, {len(segs)} caption segments", meeting_url=u,
                            platform=str(plat), tier="1", duration_seconds="", archive_slug=slug)
                append_result(row); state["govs"][gid] = "ingested"; save_state(state)
                tier1_done = True
                break
            except Exception as e:
                msg = str(e)
                bucket = "waiting on deploy" if is_new_id else "resolve failed"
                row = dict(stage=stage, gov_id=gid, gov_name=gov_name, bucket=bucket,
                            reason=f"ingest failed: {msg[:300]}", meeting_url=u,
                            platform=str(plat), tier="1", duration_seconds="", archive_slug="")
                append_result(row); state["govs"][gid] = bucket.replace(" ", "_"); save_state(state)
                tier1_done = True
                break
        else:
            tier3_candidates.append((u, str(plat), getattr(res, "video_url", None)))

    if tier1_done:
        return

    if tier3_candidates:
        best = None
        checked = []
        for u, plat, vurl in tier3_candidates:
            try:
                pr = await probe_one(u, video_url=vurl, platform=plat)
            except TelvueCapReached as e:
                fail_reasons.append(f"{u}: {e}")
                continue
            except Exception as e:
                fail_reasons.append(f"{u}: probe error: {e!r}")
                continue
            dur = pr.duration_seconds or 0
            checked.append((u, plat, vurl, dur, pr))
            if 9 * 60 <= dur <= 40 * 60:
                best = (u, plat, vurl, dur, pr)
                break
        if best is None and checked:
            checked_ok = [c for c in checked if c[4].verdict not in ("reject-dead", "reject-short")]
            pool = checked_ok or checked
            best = min(pool, key=lambda c: c[3] if c[3] else float("inf"))
        if best:
            u, plat, vurl, dur, pr = best
            from app.platforms.queue_probe import finish_candidate

            outcome = await finish_candidate(
                u, video_url=vurl, platform=plat, gov_id=gid, jurisdiction=gov_name, caller=CALLER,
            )
            if outcome.action == "rejected":
                bucket = "resolve failed"
            else:
                bucket = "queued"
            row = dict(stage=stage, gov_id=gid, gov_name=gov_name, bucket=bucket,
                        reason=f"tier 3, {outcome.action}, verdict={outcome.probe.verdict}",
                        meeting_url=u, platform=plat, tier="3",
                        duration_seconds=outcome.probe.duration_seconds or "", archive_slug="")
            append_result(row); state["govs"][gid] = bucket.replace(" ", "_"); save_state(state)
            return
        fail_reasons.append("all tier-3 candidates failed to probe")

    if yt_candidate:
        append_yt_lead(gid, gov_name, st_abbr, yt_candidate, f"{CALLER} tier 2")
        row = dict(stage=stage, gov_id=gid, gov_name=gov_name, bucket="drip", reason="tier 2 (YouTube), added to youtube_channel_leads.csv",
                    meeting_url=yt_candidate, platform="youtube", tier="2", duration_seconds="", archive_slug="")
        append_result(row); state["govs"][gid] = "drip"; save_state(state)
        return

    joined = "; ".join(fail_reasons)[:500] or "no video found"
    bucket = "TBD" if any("SHARED HOST MISMATCH" in fr for fr in fail_reasons) else "resolve failed"
    row = dict(stage=stage, gov_id=gid, gov_name=gov_name, bucket=bucket, reason=joined,
                meeting_url=rows[0]["meeting_url"], platform="", tier="", duration_seconds="", archive_slug="")
    append_result(row); state["govs"][gid] = bucket.replace(" ", "_"); save_state(state)


async def main():
    aiohttp_mod = _setup()
    from app.platforms import register_all_finders

    register_all_finders()
    registry = load_registry()
    queue_govs = load_queue_govs()
    rows = load_rows()
    groups, tbd = group_by_gov(rows, registry)
    host_gov_map = build_host_gov_map(rows)
    state = load_state()

    if not state.get("tbd_written"):
        with open(OUT / "stage4_tbd.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["gov_name", "meeting_url", "evidence", "reason"])
            for r in tbd:
                w.writerow([r.get("gov_name", ""), r.get("meeting_url", ""), r.get("evidence", "")[:200],
                            "no gov_id (or multiple candidate ids) in input"])
        state["tbd_written"] = True
        state["tbd_count"] = len(tbd)
        save_state(state)

    async with aiohttp_mod.ClientSession() as session:
        gids = sorted(groups.keys())
        lim = os.environ.get("RESOLVE_STAGE34_LIMIT")
        if lim:
            gids = gids[: int(lim)]
        total = len(gids)
        for i, gid in enumerate(gids):
            if gid in state["govs"]:
                continue
            try:
                await handle_gov(aiohttp_mod, session, gid, groups[gid], registry, queue_govs, state, host_gov_map, "stage4")
            except Exception as e:
                row = dict(stage="stage4", gov_id=gid, gov_name=groups[gid][0].get("gov_name", ""), bucket="resolve failed",
                            reason=f"unhandled error: {e!r}", meeting_url=groups[gid][0]["meeting_url"],
                            platform="", tier="", duration_seconds="", archive_slug="")
                append_result(row); state["govs"][gid] = "error"; save_state(state)
            print(f"[{i+1}/{total}] {gid} -> {state['govs'].get(gid)}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
