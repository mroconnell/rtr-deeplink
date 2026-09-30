"""Stage 3 no-video outcomes (2026-09-29): the 40 stage3_walked.csv rows
whose own walk evidence already says "with video 0" -- a confirmed,
mechanical negative (no candidate needs resolving). Per the playbook step
1 rule: write reject_reason=no-meeting-nor-video, with source and date,
only if the government has no Archive page and its current reject_reason
is blank. Checks coverage live against redtaperecordings.com, and the
current reject_reason against research/jurisdiction_coverage.csv (never
edited directly -- this only proposes rows for proposed_row_changes.csv).
"""
import asyncio, csv, datetime, json, re
from pathlib import Path
from urllib.parse import quote

BIZ = Path("/Users/mroconnell/Documents/rtr-business/.claude/worktrees/agitated-lamarr-009d82")
STAGE3 = BIZ / "research/slug_learning_2026-09-27/funnel_audit/playbook_2026-09-29/stage3_walked.csv"
REGISTRY_CSV = BIZ / "research/jurisdiction_coverage.csv"
OUT = BIZ / "research/slug_learning_2026-09-27/funnel_audit/playbook_2026-09-29/stage34"
UA = "Mozilla/5.0 (compatible; RTR-research/1.0)"
TODAY = "2026-09-29"


def load_registry():
    by_id = {}
    with open(REGISTRY_CSV) as f:
        for row in csv.DictReader(f):
            gid = (row.get("gov_id") or "").strip()
            if gid:
                by_id[gid] = row
    return by_id


_PLACE_SUFFIXES = (
    " city", " town", " township", " charter township", " village", " borough",
    " county", " cousub", " csd", " cd", " district", " school district",
    " authority",
)


def _place_core(name):
    n = (name or "").lower().split(",")[0].strip()
    n = re.sub(r"\([^)]*\)", "", n).strip()
    for suf in _PLACE_SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)].strip()
    return n


def _core_and_state(name):
    name = name or ""
    m_paren = re.search(r"\(([A-Za-z]{2})\)\s*$", name)
    parts = name.split(",")
    state = None
    if len(parts) > 1:
        state = parts[-1].strip()
    elif m_paren:
        state = m_paren.group(1)
    core = _place_core(name)
    return core, (state or "").strip().upper()


async def check_coverage(session, gov_name):
    # Fixed 2026-09-29: the API wants the bare place name ("Omaha"), not
    # the full "Omaha city, NE" string, which returns zero matches --
    # confirmed live (found mid-job on the stage4 resolve run; see
    # verify_coverage_fixed.py). Query with the stripped core name, then
    # require the label's state to match when both are known, falling
    # back to a single unverified match only when state can't be checked.
    core, st = _core_and_state(gov_name)
    if not core:
        return False, "no government name to check"
    url = f"https://redtaperecordings.com/api/jurisdictions?q={quote(core)}"
    async with session.get(url, headers={"User-Agent": UA}, timeout=30) as resp:
        st_code = resp.status
        body = await resp.text()
    try:
        matches = json.loads(body).get("matches", []) if st_code == 200 else []
    except Exception:
        matches = []
    if not matches:
        return False, "no hub found by name"

    def link_state_ok(link):
        if not st:
            return None
        return (link or "").lower().rstrip("/").endswith("-" + st.lower())

    exact = []
    for cand in matches:
        mc, mst = _core_and_state(cand.get("label", ""))
        if mc != core:
            continue
        ok = link_state_ok(cand.get("link", ""))
        if ok is True or (mst and st and mst == st):
            exact.append(cand)
    if not exact:
        core_matches = [cand for cand in matches if _core_and_state(cand.get("label", ""))[0] == core]
        if len(core_matches) == 1 and link_state_ok(core_matches[0].get("link", "")) is None:
            exact = core_matches
        else:
            return False, f"no confident hub match (core={core!r}, {len(matches)} raw matches)"
    m = exact[0]
    link = m.get("link")
    if not link:
        return False, "match had no link"
    url = f"https://redtaperecordings.com{link}"
    async with session.get(url, headers={"User-Agent": UA}, timeout=30) as resp:
        st = resp.status
        body = await resp.text()
    dates = re.findall(r"20\d\d-\d\d-\d\d", body)
    if not dates:
        return False, f"hub {link} exists but no dated page found"
    newest = max(dates)
    y, mo, d = (int(x) for x in newest.split("-"))
    newest_date = datetime.date(y, mo, d)
    stale_cutoff = datetime.date(2026, 9, 29) - datetime.timedelta(days=365 * 2)
    if newest_date >= stale_cutoff:
        return True, f"has Archive page, newest {newest}"
    return False, f"Archive page exists but stale (newest {newest}, >2y old)"


async def main():
    import aiohttp

    pat = re.compile(r"with video (\d+)")
    rows = list(csv.DictReader(open(STAGE3)))
    zero_rows = [r for r in rows if (m := pat.search(r["evidence"])) and int(m.group(1)) == 0]
    by_gov = {}
    for r in zero_rows:
        gid = (r.get("gov_id") or "").strip()
        if gid:
            by_gov.setdefault(gid, r)
    registry = load_registry()

    proposed = []
    skipped = []
    async with aiohttp.ClientSession() as session:
        for gid, r in sorted(by_gov.items()):
            gov_name = r.get("gov_name", "").strip()
            reg = registry.get(gid)
            cur_reject = (reg.get("reject_reason") if reg else "") or ""
            if cur_reject.strip():
                skipped.append((gid, gov_name, f"reject_reason already set: {cur_reject!r}"))
                continue
            covered, reason = await check_coverage(session, gov_name)
            if covered:
                skipped.append((gid, gov_name, reason))
                continue
            src = r["source_file"]
            proposed.append({
                "gov_id": gid,
                "gov_name": gov_name,
                "field": "reject_reason",
                "old_value": cur_reject,
                "new_value": "no-meeting-nor-video",
                "why": f"stage3_walked.csv walk found 0 videos among matched shows ({r['evidence'][:150]}); "
                       f"source: {src}; date: {TODAY}; coverage check: {reason}",
            })
    with open(OUT / "stage3_novideo_proposed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["gov_id", "gov_name", "field", "old_value", "new_value", "why"])
        w.writeheader()
        for p in proposed:
            w.writerow(p)
    with open(OUT / "stage3_novideo_skipped.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gov_id", "gov_name", "why_skipped"])
        for row in skipped:
            w.writerow(row)
    print(f"unique govs in the 40 zero-video rows: {len(by_gov)}")
    print(f"proposed no-video outcomes: {len(proposed)}")
    print(f"skipped (already covered or already has a reject_reason): {len(skipped)}")


if __name__ == "__main__":
    asyncio.run(main())
