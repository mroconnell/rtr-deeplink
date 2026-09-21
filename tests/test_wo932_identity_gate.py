"""WO-932: the identity gate at ingest.

Every government, host and page name below is a real one, taken from the
BACKLOG entries this work order closes or from the real inventory export
(2026-09-21). Where a test builds its own page text or its own row it says so
and says what real fact it stands on -- CLAUDE.md's synthetic-test rule.

Covers, in order:

1. `identity_gate.jurisdiction_check_hook()` -- WO-149's hook, now installed
   by default in `wo134_confirmed_hits_ingest.py`. Real rows: De Kalb city TX
   (a De Kalb, IL site) and Laverne town OK (a La Verne, CA video archive),
   the WO-912/913 hand-check cases. Plus the two-letter-WORD hazard WO-280
   found in wo146's scan, which the hook shared and which only mattered once
   the hook became default-on.
2. `identity_gate.host_name_conflict()` -- Beltrami city, MN on
   `minnesotapuc.granicus.com` (WO-190), with `hcnv.granicus.com` (Humboldt
   County NV) and the Shorewood / LMCC consortium tenant as the two that must
   keep passing, and a measured ceiling on flags over every real single-tenant
   pin in tenant_overrides.csv.
3. The resolver's mint guard: the Bracken County KY fiscal court that was
   minted as a Saskatchewan government, and the two type-initials names
   ("Oxnard School District", "Arkansas Supreme Court") from the false-state-
   code entry.
4. The same host-name flag in `hub_sweep_wo126.act_on_resolved()`, the base
   the WO-151 sweep and its followers share.
5. A repair fragment is never minted: live pages 5945 ("South, MB (Canada)",
   really a Washington fire authority) and 10852 ("North, UT"), found in the
   2026-09-21 production export while chasing the Bracken County shape.
"""

import csv
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.wo134_confirmed_hits_ingest as wo134
from app.platforms import register_all_finders
from app.platforms.models import ResolvedMeeting, TranscriptSegment
from app.utils.gov_registry import resolver
from app.utils.gov_registry.registry import government_for_id
from scripts import identity_gate
from scripts.identity_gate import (
    host_name_conflict,
    jurisdiction_check_hook,
    label_matches_name,
    state_codes_in,
    tenant_label,
)

register_all_finders()

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "app" / "utils" / "jurisdiction_data"

# Real registry ids (checked against us_places.csv / us_cousubs.csv / ca_csd.csv).
DE_KALB_TX = "us:place:4819648"
LAVERNE_OK = "us:place:4041700"
BELTRAMI_MN = "us:place:2705014"
LAKE_IN_THE_HILLS_IL = "us:place:1741183"
TRUTH_OR_CONSEQUENCES_NM = "us:place:3579840"
PONCE_DE_LEON_FL = "us:place:1258175"
CHARLESTON_SC = "us:place:4513330"


def _result(jurisdiction):
    return SimpleNamespace(jurisdiction=jurisdiction)


# --------------------------------------------------------------------------
# 1. jurisdiction_check_hook
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gov_id, unit_name, adapter_guess, named_state",
    [
        # WO-912/913 hand-check: De Kalb city TX's recorded site is De Kalb, IL's.
        (DE_KALB_TX, "De Kalb city", "De Kalb, IL", "IL"),
        # ... and Laverne town OK's recorded video archive is La Verne, CA's.
        (LAVERNE_OK, "Laverne town", "La Verne, CA", "CA"),
        # WO-149's own documented shape: a bare state code with no comma.
        (CHARLESTON_SC, "Charleston city", "Charleston WV Recreation Commission", "WV"),
    ],
)
def test_hook_rejects_a_guess_that_names_a_different_state(
    gov_id, unit_name, adapter_guess, named_state
):
    result = _result(adapter_guess)
    ok, note = jurisdiction_check_hook(result, gov_id, unit_name, "granicus", "seed")
    assert ok is False
    assert "wrong-domain-mapping" in note
    assert named_state in note
    # A rejected hit is left alone; nothing is forced onto it.
    assert result.jurisdiction == adapter_guess


def test_hook_forces_the_registry_name_when_the_state_agrees_or_is_absent():
    same_state = _result("De Kalb, TX")
    assert jurisdiction_check_hook(same_state, DE_KALB_TX, "De Kalb city", "g", "s")[0]
    assert same_state.jurisdiction == "De Kalb city"

    no_state = _result("De Kalb")
    assert jurisdiction_check_hook(no_state, DE_KALB_TX, "De Kalb city", "g", "s")[0]
    assert no_state.jurisdiction == "De Kalb city"

    blank = _result(None)
    assert jurisdiction_check_hook(blank, DE_KALB_TX, "De Kalb city", "g", "s")[0]
    assert blank.jurisdiction == "De Kalb city"


@pytest.mark.parametrize(
    "gov_id, unit_name, real_name",
    [
        # Real governments whose own names hold a two-letter word that is
        # also a state code (WO-280's list): "in" = IN, "or" = OR, "de" = DE.
        (
            LAKE_IN_THE_HILLS_IL,
            "Lake in the Hills village",
            "Lake in the Hills village",
        ),
        (
            TRUTH_OR_CONSEQUENCES_NM,
            "Truth or Consequences city",
            "Truth or Consequences city",
        ),
        (PONCE_DE_LEON_FL, "Ponce de Leon town", "Ponce de Leon town"),
    ],
)
def test_hook_does_not_read_a_two_letter_word_as_a_state(gov_id, unit_name, real_name):
    """Before WO-932 the scan upper-cased the whole guess, so each of these
    read as Indiana, Oregon or Delaware and the hook would have refused a real
    government's own meetings the moment it became default-on."""
    result = _result(real_name)
    ok, note = jurisdiction_check_hook(result, gov_id, unit_name, "granicus", "seed")
    assert ok is True, note
    assert result.jurisdiction == unit_name


def test_state_codes_in_reads_only_real_shapes():
    assert state_codes_in("Charleston, WV") == ["WV"]
    assert state_codes_in("Charleston, wv") == ["WV"]
    assert state_codes_in("Charleston WV Recreation Commission") == ["WV"]
    assert state_codes_in("Lake in the Hills village") == []
    assert state_codes_in("Portage la Prairie") == []
    # In an all-upper-case guess only the comma form counts: every word looks
    # like a code there.
    assert state_codes_in("LAKE IN THE HILLS, IL") == ["IL"]
    assert state_codes_in("LAKE IN THE HILLS") == []
    assert state_codes_in("") == []


def test_wo134_installs_the_hook_by_default():
    """Checked in a fresh interpreter: other tests (and other sweeps' import
    side effects) legitimately reassign `wo134.JURISDICTION_CHECK_HOOK`, so
    reading it in this process would test the test order, not the default."""
    code = (
        "import scripts.wo134_confirmed_hits_ingest as w, scripts.identity_gate as g;"
        "print(w.JURISDICTION_CHECK_HOOK is g.jurisdiction_check_hook)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.stdout.strip().splitlines()[-1] == "True", out.stderr[-500:]


def test_wo149_still_exposes_the_same_hook_under_its_old_name():
    """wo912_wo913_ingest_confirmed.py, wo218 and wo223 do
    `wo149.jurisdiction_check_hook`. wo149 needs the rtr-discovery checkout to
    import, so this reads the file instead of importing it."""
    text = (REPO_ROOT / "scripts" / "wo149_county_ladder_sweep.py").read_text()
    assert "from scripts.identity_gate import jurisdiction_check_hook" in text
    assert "def jurisdiction_check_hook" not in text


# process_row, through the default hook ------------------------------------


def _row(gov_id, unit_name, source_url):
    return {
        "gov_id": gov_id,
        "unit_name": unit_name,
        "homepage": "",
        "hop2_urls": "",
        "hit_source_urls": f"granicus={source_url}",
    }


def _wire(monkeypatch, result, source_url):
    async def fake_locate(session, platform, hit_url, hop2_urls, homepage):
        return source_url, ""

    async def fake_resolve_seed(session, platform, seed_url):
        return result, source_url, False

    calls = []

    async def fake_ingest(session, payload, input_url_normalized):
        calls.append(payload)
        return {"slug": "x", "url": "/m/x", "created": True}

    monkeypatch.setattr(wo134, "locate_platform_url", fake_locate)
    monkeypatch.setattr(wo134, "resolve_seed", fake_resolve_seed)
    monkeypatch.setattr(wo134, "_ingest_with_retry", fake_ingest)
    monkeypatch.setattr(wo134, "maybe_write_tenant_override", lambda *a, **k: None)
    monkeypatch.setattr(wo134, "_seen_keys", set())
    # The default the module ships with, restored for this test whatever ran before.
    monkeypatch.setattr(wo134, "JURISDICTION_CHECK_HOOK", jurisdiction_check_hook)
    monkeypatch.setattr(wo134, "IDENTITY_CHECK_HOOK", None)
    return calls


def _meeting(source_url, title, jurisdiction):
    # Synthetic transcript text; the government, host, title and state
    # strings around it are the real ones each test names.
    return ResolvedMeeting(
        platform="granicus",
        source_url=source_url,
        title=title,
        date="2026-01-01",
        jurisdiction=jurisdiction,
        segments=[TranscriptSegment(start=0.0, end=1.0, text="hello")],
    )


async def test_process_row_refuses_a_de_kalb_tx_row_served_by_de_kalb_il(monkeypatch):
    url = "https://dekalb-il-wo932.granicus.com/MediaPlayer.php?view_id=1&clip_id=1"
    result = _meeting(url, "City Council Regular Meeting", "De Kalb, IL")
    calls = _wire(monkeypatch, result, url)

    out = await wo134.process_row(
        None, _row(DE_KALB_TX, "De Kalb city", url), set(), "test"
    )

    assert out.outcome == "skipped"
    assert "wrong-domain-mapping" in out.reason
    assert calls == []  # nothing was sent to the Archive


async def test_process_row_still_ingests_a_matching_row_and_forces_the_name(
    monkeypatch,
):
    url = "https://dekalbtx-wo932.granicus.com/MediaPlayer.php?view_id=1&clip_id=1"
    result = _meeting(url, "City Council Regular Meeting", "De Kalb, TX")
    calls = _wire(monkeypatch, result, url)

    out = await wo134.process_row(
        None, _row(DE_KALB_TX, "De Kalb city", url), set(), "test"
    )

    assert out.outcome == "ingested_tier1_2"
    assert calls[0]["gov_id"] == DE_KALB_TX
    assert calls[0]["jurisdiction"] == "De Kalb city"


async def test_process_row_flags_the_beltrami_puc_host_without_blocking(monkeypatch):
    """The real WO-190 case: Beltrami city, MN resolved a clip on
    `minnesotapuc.granicus.com`, a 2013 Minnesota Public Utilities Commission
    hearing. The title names no place, so the text checks pass; the host is
    the only signal. It is flagged on the row's reason, and the row still
    goes through -- flag first, not skip (the entry's own constraint)."""
    url = "https://minnesotapuc.granicus.com/MediaPlayer.php?view_id=2&clip_id=27"
    result = _meeting(url, "PUC Agenda Meeting on 2013-06-06 9:30 AM", "")
    calls = _wire(monkeypatch, result, url)

    out = await wo134.process_row(
        None, _row(BELTRAMI_MN, "Beltrami city", url), set(), "test"
    )

    assert out.outcome == "ingested_tier1_2"
    assert len(calls) == 1
    assert "host-name-review" in out.reason
    assert "minnesotapuc" in out.reason


# --------------------------------------------------------------------------
# 2. host_name_conflict
# --------------------------------------------------------------------------


def test_the_real_beltrami_puc_host_is_flagged():
    reason = host_name_conflict(
        "minnesotapuc.granicus.com", "granicus", "Beltrami city", "MN"
    )
    assert reason is not None
    assert reason.startswith("host-name-review")
    assert "minnesotapuc" in reason and "Beltrami" in reason


@pytest.mark.parametrize(
    "host, platform, gov_name, state",
    [
        # Named in the entry: an abbreviated tenant that passed a manual
        # re-check and "must keep passing".
        ("hcnv.granicus.com", "granicus", "Humboldt County", "NV"),
        # Real single-tenant hosts whose label holds the place name.
        ("mandannd.portal.civicclerk.com", "civicclerk", "Mandan city", "ND"),
        ("abbotsford.civicweb.net", "civicweb", "Abbotsford", "BC"),
        # The same-name trap this check CANNOT see (and the raw-page check
        # in wo145 can): a Lakewood tenant's own host names Lakewood whether
        # it is Colorado's or New Jersey's.
        ("pub-lakewood.escribemeetings.com", "escribe", "Lakewood city", "CO"),
    ],
)
def test_real_tenants_that_name_the_government_pass(host, platform, gov_name, state):
    assert host_name_conflict(host, platform, gov_name, state) is None


def test_the_shorewood_lmcc_consortium_tenant_never_flags():
    """Shorewood city, MN's real Cablecast clip is on the shared Lake
    Minnetonka consortium host. The label shares no word with "Shorewood" and
    is completely legitimate (the entry's confirmed example)."""
    assert (
        host_name_conflict(
            "reflect-lmcc.cablecast.tv", "cablecast", "Shorewood city", "MN"
        )
        is None
    )


def test_an_unlisted_bare_cablecast_host_is_flagged_with_the_consortium_hint():
    # Orion Township, MI's real pin, host `reflect-ontv.cablecast.tv`: no name
    # word in the label. Flagged for a person to read, not treated as wrong.
    reason = host_name_conflict(
        "reflect-ontv.cablecast.tv", "cablecast", "Orion charter township", "MI"
    )
    assert reason is not None
    assert "consortium" in reason


@pytest.mark.parametrize(
    "host",
    [
        "www.youtube.com",  # shared video host: says nothing about the government
        "youtu.be",
        "www.bambergcounty.sc.gov",  # the government's own domain
        "videoplayer.telvue.com",  # shared player host, pinned per video
        "play.champds.com",
        "public.destinyhosted.com",
        "archive-stream.granicus.com",  # vendor infrastructure, not a tenant
        "",
    ],
)
def test_hosts_that_are_not_a_single_tenant_never_flag(host):
    assert host_name_conflict(host, "", "Beltrami city", "MN") is None


def test_tenant_label_strips_the_platform_suffix():
    assert tenant_label("hcnv.granicus.com") == "hcnv"
    assert tenant_label("mandannd.portal.civicclerk.com") == "mandannd"
    assert tenant_label("pub-lakewood.escribemeetings.com") == "pub-lakewood"
    assert tenant_label("www.granicus.com") == ""
    assert tenant_label("granicus.com") == ""


def test_label_matches_name_accepts_initials_and_state():
    assert label_matches_name("hcnv", "Humboldt County", "NV")  # initials + state
    assert label_matches_name("beltramimn", "Beltrami city", "MN")  # name + state
    assert not label_matches_name("minnesotapuc", "Beltrami city", "MN")


def test_flag_rate_over_every_real_single_tenant_pin_stays_low():
    """Measured 2026-09-21 over tenant_overrides.csv: 58 of 1,281 pins on a
    single-tenant vendor host flag (4.5%), all of them abbreviated tenants a
    person can read at a glance (ccsf = San Francisco, stpete = St.
    Petersburg, lawa = Los Angeles World Airports). The ceiling is a guard
    against the matching rules drifting into flagging most real tenants; it
    is not a claim that each flag is wrong."""
    tested = flagged = 0
    with (DATA / "tenant_overrides.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not tenant_label(row["tenant_host"]):
                continue
            gov = government_for_id(row["gov_id"])
            if gov is None:
                continue
            tested += 1
            if host_name_conflict(row["tenant_host"], "", gov.gov_name, gov.state):
                flagged += 1
    assert tested > 1000
    assert flagged / tested < 0.08, (flagged, tested)


# --------------------------------------------------------------------------
# 3. the resolver's mint guard (Bracken County KY; type-initials names)
# --------------------------------------------------------------------------


def test_bracken_county_ky_fiscal_court_is_not_minted_as_a_saskatchewan_government():
    """WO-153 (2026-09-10) found this live as
    `rtr:ca:sk:bracken-county-ky-fiscal-court`. The repair step trimmed the
    channel name to "Bracken" -- a Saskatchewan place, and a county (not a
    place) in Kentucky -- and rung 3 then minted the RAW name with that
    string's province. The page's own text says KY."""
    for host in (None, "example.com"):
        match = resolver.resolve_government(
            "Bracken County KY Fiscal Court", tenant_host=host
        )
        assert match.tier == resolver.TIER_UNRESOLVED
        assert not match.gov_id.startswith("rtr:ca:")
        assert "KY" in match.evidence


def test_bracken_video_on_youtube_keys_by_its_pin_and_an_unpinned_video_stays_blank():
    """On the shared YouTube host the ladder cannot mint at all since WO-210
    (rung 1b), so the live Bracken page needed the pin, which
    tenant_overrides.csv carries: `www.youtube.com,youtube:xC4ICFWd9E4,
    us:county:21023`. A different video from the same channel has no pin and
    stays unidentified rather than being guessed."""
    pinned = resolver.resolve_government(
        "Bracken County KY Fiscal Court",
        tenant_host="www.youtube.com",
        path="/watch?v=xC4ICFWd9E4",
        page_hints={"platform": "youtube", "external_id": "xC4ICFWd9E4"},
    )
    assert pinned.gov_id == "us:county:21023"
    assert pinned.tier == resolver.TIER_PINNED

    other = resolver.resolve_government(
        "Bracken County KY Fiscal Court",
        tenant_host="www.youtube.com",
        path="/watch?v=AAAAAAAAAAA",
        page_hints={"platform": "youtube", "external_id": "AAAAAAAAAAA"},
    )
    assert other.gov_id.startswith("rtr:unknown:")


@pytest.mark.parametrize(
    "text, code",
    [
        ("Bracken County KY Fiscal Court", "KY"),
        ("Multnomah County Board", ""),
        ("Lake in the Hills village", ""),
        ("Truth or Consequences city", ""),
        ("Portage la Prairie", ""),
        ("County Or Township", ""),  # title-case word, not a code
        ("", ""),
    ],
)
def test_embedded_state_code_reads_only_a_code_after_a_place_type_word(text, code):
    assert resolver._embedded_state_code(text) == code


def test_a_trailing_state_the_page_wrote_is_never_second_guessed():
    """The guard only refuses a state that came from the repair step. A
    government written with its own trailing state still resolves normally."""
    match = resolver.resolve_government("Fresno County, CA")
    assert match.gov_id == "us:county:06019"


@pytest.mark.parametrize("name", ["Oxnard School District", "Arkansas Supreme Court"])
@pytest.mark.parametrize("host", [None, "example.com"])
def test_type_phrase_names_are_never_minted_with_their_own_initials_as_a_state(
    name, host
):
    """The false-state-code entry's two live pages. Its diagnosis (the code was
    lifted from the name text) was wrong: it came from the subdomain reader,
    fixed 2026-09-10 (#836). The name text on its own never mints them --
    unresolved is the answer -- and this pins that."""
    match = resolver.resolve_government(name, tenant_host=host)
    assert match.tier == resolver.TIER_UNRESOLVED
    assert not match.gov_id.startswith(("rtr:us:sc:", "rtr:us:sd:"))


def test_no_committed_minted_id_carries_the_initials_of_its_own_type_phrase():
    """Data guard for the same entry. Two stale rows from before the
    2026-09-10 fix are still in governments.csv (the two live pages the entry
    named); both have replacement ids and pins, and hub_slug_aliases.csv still
    points at them, so they stay. A THIRD such row would be a new mint of the
    same bug."""
    known_stale = {
        "rtr:us:sc:arkansas-supreme-court",
        "rtr:us:sd:oxnard-school-district",
    }
    found = set()
    with (DATA / "governments.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gov_id = row["gov_id"]
            if not gov_id.startswith("rtr:"):
                continue
            parts = gov_id.split(":")
            if len(parts) >= 4 and resolver._state_is_type_initials(
                row["gov_name"], parts[2].upper()
            ):
                found.add(gov_id)
    assert found == known_stale


def test_module_documents_its_own_limits():
    # The module docstring is what a later reader of a review flag opens.
    assert "REVIEW" in identity_gate.__doc__
    assert "Lake in the Hills" in identity_gate.__doc__


# --------------------------------------------------------------------------
# 4. the same flag in hub_sweep_wo126, the base every sweep built on it shares
# --------------------------------------------------------------------------


class _EmptyIndex:
    """`hs.DedupeIndex`'s two methods act_on_resolved() calls, with nothing
    covered and nothing queued."""

    queued = set()

    def covered(self, result, meeting_url):
        return None

    def in_queue(self, url):
        return False


async def _hs_act(gov, url, platform):
    import scripts.hub_sweep_wo126 as hs

    result = _meeting(url, "PUC Agenda Meeting on 2013-06-06 9:30 AM", "")
    lead = hs.Found(url=url, platform=platform, found_on="https://example.invalid/")
    res = hs.Result()
    await hs.act_on_resolved(
        None, gov, lead, result, url, False, _EmptyIndex(), res, True
    )
    return hs, res


async def test_hub_sweep_flags_the_beltrami_puc_host_and_still_acts():
    import scripts.hub_sweep_wo126 as hs

    gov = hs.Gov(BELTRAMI_MN, "Beltrami", "MN", "", "", "")
    url = "https://minnesotapuc.granicus.com/MediaPlayer.php?view_id=2&clip_id=27"
    hs, res = await _hs_act(gov, url, "granicus")
    assert res.outcome == "dry_run_tier1_2"  # flag only: the row still went on
    assert "host-name-review" in hs._with_host_flag(res)


async def test_hub_sweep_says_nothing_about_a_matching_host():
    import scripts.hub_sweep_wo126 as hs

    gov = hs.Gov("us:place:3849900", "Mandan", "ND", "", "", "")
    url = "https://mandannd.portal.civicclerk.com/event/344/media"
    hs, res = await _hs_act(gov, url, "civicclerk")
    assert hs._with_host_flag(res) == res.detail
    assert "host-name-review" not in hs._with_host_flag(res)


# --------------------------------------------------------------------------
# 5. a repair fragment is never minted as a government ("South", "North")
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, host, forbidden_prefix",
    [
        # Real live page 5945 (2026-09-21 export), shown to readers as
        # "South, MB (Canada)": a Washington fire authority on Granicus.
        (
            "South Snohomish County Fire and Rescue RFA",
            "southsnofire.granicus.com",
            "rtr:ca:",
        ),
        (
            "South Snohomish County Fire and Rescue RFA",
            "example.com",
            "rtr:ca:",
        ),
        # Real live page 10852, shown as "North, UT": a Utah public safety
        # department from the Utah Public Notice Website.
        ("North Valley Public Safety Department, Utah", None, "rtr:us:ut:north"),
    ],
)
def test_a_repair_fragment_is_not_minted_as_a_government(name, host, forbidden_prefix):
    match = resolver.resolve_government(name, tenant_host=host)
    assert match.tier == resolver.TIER_UNRESOLVED
    assert not match.gov_id.startswith(forbidden_prefix)


def test_looks_like_a_name_rejects_only_a_bare_compass_word():
    assert resolver._looks_like_a_name("South") is False
    assert resolver._looks_like_a_name("Central") is False
    assert resolver._looks_like_a_name("Leduc") is True
    assert resolver._looks_like_a_name("South Snohomish County Fire") is True
    assert resolver._looks_like_a_name("West County Wastewater District") is True


def test_a_real_place_with_a_compass_name_still_resolves_from_the_tables():
    """The guard sits at the mint, after the national tables. West, TX is a
    real city there and never reaches it."""
    match = resolver.resolve_government("West, TX")
    assert match.tier == resolver.TIER_REGISTRY
    assert match.gov_id.startswith("us:place:")


def test_no_committed_minted_id_is_a_bare_compass_word():
    """One stale row exists: `rtr:ca:mb:south`, the id of the live page named
    above. It stays until that page is re-keyed (deleting the row first would
    leave the page pointing at nothing). A second such row is a new mint of
    the same bug."""
    found = set()
    with (DATA / "governments.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gov_id = row["gov_id"]
            if gov_id.startswith("rtr:") and (
                gov_id.split(":")[-1] in resolver._BARE_DIRECTION_WORDS
            ):
                found.add(gov_id)
    assert found == {"rtr:ca:mb:south"}
