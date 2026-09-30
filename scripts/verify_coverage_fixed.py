"""Re-check coverage for every stage4 government NOT already marked
skipped_covered/skipped_queued, using a corrected query (the original
check_coverage() query bug: it queried the API with the full "Omaha
city, NE" string, which returns zero matches -- the API wants just the
place name, e.g. "Omaha"). Confirmed live: query "Omaha" -> exact hit;
query "Omaha city, NE" -> no matches. This re-check finds any government
that was actually already covered but got routed as if uncovered.
"""
import asyncio, csv, json, re
from pathlib import Path
from urllib.parse import quote

BIZ = Path("/Users/mroconnell/Documents/rtr-business/.claude/worktrees/agitated-lamarr-009d82")
STAGE34 = BIZ / "research/slug_learning_2026-09-27/funnel_audit/playbook_2026-09-29/stage34"
UA = "Mozilla/5.0 (compatible; RTR-research/1.0)"

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


async def check_coverage_fixed(session, gov_name):
    core, st = _core_and_state(gov_name)
    if not core:
        return False, "no government name to check", None
    url = f"https://redtaperecordings.com/api/jurisdictions?q={quote(core)}"
    async with session.get(url, headers={"User-Agent": UA}, timeout=30) as resp:
        status = resp.status
        body = await resp.text()
    try:
        matches = json.loads(body).get("matches", []) if status == 200 else []
    except Exception:
        matches = []
    def link_state_ok(link):
        if not st:
            return None  # unknown -- can't verify
        return (link or "").lower().rstrip("/").endswith("-" + st.lower())

    exact = []
    for m in matches:
        mc, mst = _core_and_state(m.get("label", ""))
        if mc != core:
            continue
        ok = link_state_ok(m.get("link", ""))
        if ok is True or (mst and st and mst == st):
            exact.append(m)
    unverified = False
    if not exact:
        core_matches = [m for m in matches if _core_and_state(m.get("label", ""))[0] == core]
        if len(core_matches) == 1 and link_state_ok(core_matches[0].get("link", "")) is None:
            exact = core_matches
            unverified = True
        else:
            return False, f"no confident hub match for {gov_name!r} (core={core!r}, {len(matches)} raw matches)", None
    link = exact[0].get("link")
    if not link:
        return False, "match had no link", None
    url = f"https://redtaperecordings.com{link}"
    async with session.get(url, headers={"User-Agent": UA}, timeout=30) as resp:
        body = await resp.text()
    dates = re.findall(r"20\d\d-\d\d-\d\d", body)
    if not dates:
        return False, f"hub {link} exists but no dated page found", None
    newest = max(dates)
    tag = "HAS ARCHIVE PAGE (state unverified)" if unverified else "HAS ARCHIVE PAGE"
    return True, f"{tag} (newest {newest}) link={link}", newest


async def main():
    import aiohttp

    rows = list(csv.DictReader(open(STAGE34 / "results.csv")))
    to_check = [r for r in rows if r["bucket"] not in ("skipped: covered",) and r["stage"] == "stage4"]
    print(f"re-checking {len(to_check)} rows (stage4, not already skipped_covered)")
    discrepancies = []
    async with aiohttp.ClientSession() as session:
        for r in to_check:
            covered, reason, newest = await check_coverage_fixed(session, r["gov_name"])
            if covered:
                discrepancies.append((r["gov_id"], r["gov_name"], r["bucket"], reason))
    print(f"discrepancies found: {len(discrepancies)}")
    with open(STAGE34 / "coverage_recheck_discrepancies.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gov_id", "gov_name", "original_bucket", "actual_coverage"])
        for d in discrepancies:
            w.writerow(d)
            print(d)


if __name__ == "__main__":
    asyncio.run(main())
