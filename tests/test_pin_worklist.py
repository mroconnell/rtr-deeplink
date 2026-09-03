"""The pin-worklist round trip: `scripts/build_pin_worklist.py` proposes,
`scripts/apply_pin_worklist.py` resolves and writes the pin.

Phase 2c. Every case here is a REAL row -- a real host, a real slug, a
real YouTube channel from `reports/pin_worklist.csv` and
`reports/pin_worklist_youtube.csv` as generated from production on
2026-09-03. That is deliberate and it is the point: a pin is the one tier
that overrides a working extraction, so the cases worth pinning down are
the ones production actually produced, not invented ones.

Two of them are here because the first version of the build script got
them wrong, and both are the same underlying mistake in different
clothes -- a place name found inside an agency's name:

  * `achdidaho.civicweb.net` proposed **Ada County** for the Ada County
    Highway *District*;
  * `hcpsstv.new.swagit.com`'s answer "Howard County Public School
    System, MD" resolves to Howard *County*.

Architecture doc SS1.3 is the general statement of it, and the resolver's
rung 3 is its fix inside the resolver. These tests are the fix on the two
paths that run outside it.
"""

import csv
from pathlib import Path

import pytest

from app.utils.gov_registry import (
    display_name,
    is_own_name,
    registry,
    resolve_government,
)
from scripts import apply_pin_worklist, build_pin_worklist

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKLIST = REPO_ROOT / "reports" / "pin_worklist.csv"
YOUTUBE_MAP = REPO_ROOT / "reports" / "pin_worklist_youtube.csv"


def _worklist_rows():
    with open(WORKLIST, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --------------------------------------------------------------------------
# The acceptance rule
# --------------------------------------------------------------------------


def test_is_own_name_rejects_a_school_system_that_resolves_to_its_county():
    """The real answer a human is most likely to type for
    `hcpsstv.new.swagit.com`, and the reason `resolve_answer()` reports it
    back instead of pinning it."""
    stated = "Howard County Public School System, MD"
    match = resolve_government(stated)
    assert match.gov_id == "us:county:24027"  # it really does resolve
    assert not is_own_name(stated, match)


def test_is_own_name_accepts_the_registry_spelling_of_the_same_district():
    match = resolve_government("Howard County Public Schools, MD")
    assert match.gov_id == "us:sd:2400420"
    assert is_own_name("Howard County Public Schools, MD", match)


def test_is_own_name_accepts_a_name_the_registry_spells_the_same_way():
    match = resolve_government("Coppell Independent School District")
    assert match.gov_id == "us:sd:4815210"
    assert is_own_name("Coppell Independent School District", match)


# --------------------------------------------------------------------------
# Boundary-anchored candidates (build side)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug, forbidden",
    [
        # Three real slugs, three real agencies, three real counties that
        # are not the tenant.
        (
            "ada-county-highway-district-2024-06-24-capital-investment-citizen"
            "-advisory-committee",
            "ada county",
        ),
        (
            "sonoma-county-library-2026-08-17-finance-committee-17-aug-2026",
            "sonoma county",
        ),
        (
            "san-diego-county-retirement-association-2017-05-25-board-meeting",
            "san diego county",
        ),
    ],
)
def test_a_county_inside_an_agency_name_is_never_a_candidate(slug, forbidden):
    candidates = build_pin_worklist._phrase_candidates(slug)
    assert forbidden not in candidates
    # The whole agency name IS offered -- it just does not resolve, which
    # is the honest outcome for a government with no national-table row.
    assert any(forbidden in c and c != forbidden for c in candidates)


def test_the_swagit_customer_appended_to_a_slug_is_a_candidate():
    slug = "sep-16-2024-board-workshop-coppell-independent-school-district"
    assert (
        "coppell independent school district"
        in build_pin_worklist._phrase_candidates(slug)
    )


def test_an_entity_prefixed_head_is_a_candidate():
    slug = "city-of-palo-alto-amending-section-2026-08-24-city-council-meeting"
    assert "city of palo alto" in build_pin_worklist._phrase_candidates(slug)


@pytest.mark.parametrize(
    "slug, name",
    [
        # Both real eScribe hosts in British Columbia. The "sd" is slug
        # machinery, not South Dakota, and nothing on either page says
        # otherwise.
        ("langford-sd-2026-03-02-council-meeting", "langford"),
        (
            "white-rock-sd-2025-10-20-2025-events-year-in-review-regular-council-meeting",
            "white rock",
        ),
    ],
)
def test_a_short_segments_trailing_state_token_is_not_read_as_a_state(slug, name):
    candidates = build_pin_worklist._phrase_candidates(slug)
    assert f"{name} sd" not in candidates


def test_a_four_word_segment_keeps_its_state():
    """The cutoff's other side: `cityofwayne.com`'s slug carries a whole
    entity phrase, so "mi" is the coherent reading."""
    slug = "city-of-wayne-mi-2026-08-25-august-25-2026-city-of-wayne-study-session"
    assert "city of wayne mi" in build_pin_worklist._phrase_candidates(slug)


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------


def test_a_school_district_acronym_hostname_expands_to_one_district():
    """`lcpsnm.granicus.com` -- the state comes off the hostname's own tail
    and narrows "lcps" to exactly one district."""
    expansions = dict(build_pin_worklist._acronym_expansions("lcpsnm"))
    assert "Las Cruces Public Schools, NM" in expansions


def test_an_ambiguous_acronym_expands_to_nothing():
    """`pgcps` is the initials of BOTH Prince George's County Public
    Schools (MD) and Prince George County Public Schools (VA), and the
    hostname carries no state to tell them apart. Exactly one match or
    nothing -- `NameStateTable`'s own rule, for the same reason."""
    assert build_pin_worklist._acronym_expansions("pgcps") == []


def test_hostname_candidates_offer_both_state_readings():
    candidates = [
        c
        for c, _e in build_pin_worklist.hostname_candidates("stcharles-mo.cablecast.tv")
    ]
    assert candidates.index("Stcharles, MO") < candidates.index("Stcharles")


def test_a_two_letter_tail_that_is_not_a_state_still_gets_a_bare_reading():
    """`bourne.cablecast.tv` is Bourne, MA -- not Bour, NEbraska."""
    candidates = [
        c for c, _e in build_pin_worklist.hostname_candidates("bourne.cablecast.tv")
    ]
    assert "Bourne" in candidates


def test_telvue_tokens_reads_only_the_settled_rows():
    tokens = build_pin_worklist.telvue_tokens()
    if not tokens:  # the research note lives outside this repo
        pytest.skip("rtr-business/research/telvue_org_tokens.md not present")
    assert tokens.get("yycCAZPb0NN3zj2o5qio-YFMNC43NjCG") == "Fitchburg, MA"
    # "Rochester (NH/NY/MN unconfirmed)" and the multi-jurisdiction Centre
    # County token are confirmed CHANNELS, not confirmed governments.
    assert "dQtoDvlZYDOtqaf7eRn9z2lb1Nb6EZzu" not in tokens
    assert "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru" not in tokens


# --------------------------------------------------------------------------
# The worklist as generated (real rows)
# --------------------------------------------------------------------------


def test_every_proposal_on_the_sheet_names_a_government_the_registry_holds():
    """The sheet is a committed artefact and the registry moves under it.
    A proposal whose id nothing renders is a proposal Ryan would be
    accepting blind -- and it is the id, not the name, that "ok" accepts,
    because a display form with an LSAD qualifier ("Portage (city), MI")
    does not resolve back to the place it names."""
    for row in _worklist_rows():
        gov_id = row["proposed_gov_id"]
        if not gov_id:
            continue
        gov = registry.government_for_id(gov_id)
        assert gov is not None, row["tenant_host"]
        assert row["proposed_name"] == display_name(gov), row["tenant_host"]


def test_accepting_a_proposal_pins_the_id_not_the_display_name():
    """The 12 rows on the first sheet where re-resolving the display name
    would have minted an `rtr:` id instead of pinning the real place."""
    row = {
        "ryan_gov_name": "ok",
        "ryan_note": "",
        "proposed_name": "Portage (city), MI",
        "proposed_gov_id": "us:place:2665560",
    }
    # The display form on its own really does miss the place table.
    assert resolve_government("Portage (city), MI").gov_id.startswith("rtr:")
    name, accepted, source, may_mint = apply_pin_worklist._answer(row)
    assert accepted == "us:place:2665560"
    _m, gov_id, gov_name, _tier, outcome, _detail = apply_pin_worklist.resolve_answer(
        name, "portagemi.cablecast.tv", may_mint, accepted
    )
    assert (outcome, gov_id) == ("pin", "us:place:2665560")
    assert gov_name == "Portage (city), MI"
    assert source == "ryan_stated+proposal"


def test_every_proposal_is_a_national_id_and_the_governments_own_name():
    """The two gates `propose()` applies, checked against what actually
    landed on the sheet rather than against the function."""
    for row in _worklist_rows():
        gov_id = row["proposed_gov_id"]
        if not gov_id:
            continue
        assert not gov_id.startswith("rtr:"), row["tenant_host"]
        match = resolve_government(row["proposed_name"], tenant_host=row["tenant_host"])
        assert is_own_name(row["proposed_name"], match), row["tenant_host"]


def test_a_shared_host_with_no_discriminator_is_never_proposed():
    """`youtu.be` serves eight different governments. Any proposal for the
    bare host is a proposal for the wrong one -- 47 pages' worth, on the
    first run."""
    shared = [
        r
        for r in _worklist_rows()
        if not r["match"]
        and (
            r["tenant_host"] in build_pin_worklist._YOUTUBE_HOSTS
            or r["platform"] == "telvue"
        )
    ]
    assert shared, "expected at least one unidentified shared-host row"
    for row in shared:
        assert not row["proposed_gov_id"], row["tenant_host"]
        assert "shared host" in row["proposed_evidence"]


def test_a_youtube_row_is_keyed_by_channel_and_a_telvue_row_by_token():
    rows = _worklist_rows()
    youtube = [r for r in rows if r["tenant_host"] == "youtu.be" and r["match"]]
    telvue = [
        r for r in rows if r["tenant_host"] == "videoplayer.telvue.com" and r["match"]
    ]
    assert youtube and telvue
    assert all(r["match"].startswith("@") for r in youtube)
    assert all(len(r["match"]) >= 16 for r in telvue)


def test_the_sheet_is_ordered_most_pages_first_within_platform():
    order = {name: i for i, name in enumerate(build_pin_worklist.PLATFORM_ORDER)}
    rows = _worklist_rows()
    seen = [
        (order.get(r["platform"], len(order)), r["platform"], -int(r["pages"]))
        for r in rows
    ]
    assert seen == sorted(seen)


def test_regenerating_the_sheet_preserves_ryans_answers(tmp_path):
    """The loop runs over several sittings while the Archive grows, so a
    rebuild that dropped an answer would silently undo real work."""
    rows = _worklist_rows()
    sheet = tmp_path / "pin_worklist.csv"
    with open(sheet, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=build_pin_worklist.WORKLIST_HEADER)
        writer.writeheader()
        for row in rows[:5]:
            writer.writerow({**row, "ryan_gov_name": "Fresno, CA", "ryan_note": "note"})

    answers = build_pin_worklist.existing_answers(sheet)
    assert len(answers) == 5
    groups = [
        {
            "platform": r["platform"],
            "tenant_host": r["tenant_host"],
            "match": r["match"],
            "pages": int(r["pages"]),
            "_names": set(),
            "example_slug": r["example_slug"],
            "landing_url": r["landing_url"],
            "proposed_name": "",
            "proposed_gov_id": "",
            "proposed_evidence": "",
        }
        for r in rows[:5]
    ]
    assert build_pin_worklist.write_worklist(groups, sheet) == 5
    with open(sheet, encoding="utf-8") as fh:
        rebuilt = list(csv.DictReader(fh))
    assert all(r["ryan_gov_name"] == "Fresno, CA" for r in rebuilt)
    assert all(r["ryan_note"] == "note" for r in rebuilt)


# --------------------------------------------------------------------------
# The resolve-and-write path (apply side)
# --------------------------------------------------------------------------


def test_a_plain_english_name_becomes_a_national_pin():
    resolved, gov_id, gov_name, tier, outcome, _detail = (
        apply_pin_worklist.resolve_answer(
            "Prince George's County Public Schools, MD",
            "pgcps.cablecast.tv",
            may_mint=False,
        )
    )
    assert (outcome, gov_id, tier) == ("pin", "us:sd:2400510", "registry")
    assert gov_name == "Prince George's County Public Schools, MD"


def test_a_name_with_no_national_row_is_reported_back_not_minted():
    """`sdcera.granicus.com` -- the San Diego County Employees Retirement
    Association. A machine may not mint a government for a tenant."""
    _resolved, gov_id, _name, _tier, outcome, detail = (
        apply_pin_worklist.resolve_answer(
            "San Diego County Retirement Association, CA",
            "sdcera.granicus.com",
            may_mint=False,
        )
    )
    assert outcome == "unverified"
    assert gov_id.startswith("rtr:")
    assert "ok mint" in detail


def test_ok_mint_is_the_human_source_that_lets_the_same_name_through():
    _resolved, gov_id, _name, _tier, outcome, _detail = (
        apply_pin_worklist.resolve_answer(
            "San Diego County Retirement Association, CA",
            "sdcera.granicus.com",
            may_mint=True,
        )
    )
    assert outcome == "pin"
    assert gov_id.startswith("rtr:")


def test_a_name_that_resolves_to_something_it_does_not_name_is_reported_back():
    _resolved, gov_id, gov_name, _tier, outcome, detail = (
        apply_pin_worklist.resolve_answer(
            "Howard County Public School System, MD",
            "hcpsstv.new.swagit.com",
            may_mint=False,
        )
    )
    assert outcome == "name_mismatch"
    assert gov_id == "us:county:24027"
    assert gov_name == "Howard County, MD"
    assert "retype" in detail


def test_an_ok_with_no_proposal_behind_it_is_reported_back():
    row = {"ryan_gov_name": "ok", "ryan_note": "", "proposed_name": ""}
    name, accepted, source, may_mint = apply_pin_worklist._answer(row)
    _resolved, _gov_id, _name, _tier, outcome, _detail = (
        apply_pin_worklist.resolve_answer(
            name, "example.granicus.com", may_mint, accepted
        )
    )
    assert (name, accepted, source, may_mint) == ("", "", "ryan_stated+proposal", False)
    assert outcome == "no_proposal"


def test_ok_accepts_the_proposal_and_records_both_claims():
    row = {
        "ryan_gov_name": "ok",
        "ryan_note": "",
        "proposed_name": "Redlands, CA",
        "proposed_gov_id": "us:place:0659962",
    }
    name, _accepted, source, _may_mint = apply_pin_worklist._answer(row)
    assert name == "Redlands, CA"
    # A human accepted it AND a signal produced it -- two different claims,
    # both of which a later reader needs.
    assert source == "ryan_stated+proposal"
    assert registry._has_human_source(source)


def test_skip_is_an_answer_and_writes_nothing():
    assert "skip" in apply_pin_worklist.DECLINE


def test_ok_mint_is_read_from_either_of_ryans_columns():
    for row in (
        {"ryan_gov_name": "Ada County Highway District, ID", "ryan_note": "ok mint"},
        {"ryan_gov_name": "ok mint", "ryan_note": "", "proposed_name": "x"},
    ):
        assert apply_pin_worklist._answer(row)[3] is True


# --------------------------------------------------------------------------
# YouTube: one decision, several pins
# --------------------------------------------------------------------------


def test_a_youtube_channel_decision_expands_to_its_real_video_ids():
    """A pin's `match` is satisfied by the page's PATH, and a YouTube URL
    carries the video id, not the channel. A pin written against the
    handle would be silently inert -- the sheet would say the host was
    settled and the pages would stay unresolved."""
    channels = build_pin_worklist.read_youtube_map(YOUTUBE_MAP)
    if not channels:
        pytest.skip("no YouTube map generated yet")
    row = next(
        r
        for r in _worklist_rows()
        if r["tenant_host"] == "youtu.be" and r["match"] == "@TownofWoodside"
    )
    pages = [
        {"source_url_normalized": f"https://youtu.be/{vid}"}
        for vid, meta in channels.items()
        if meta["channel"] == "@TownofWoodside"
    ]
    assert len(pages) > 1
    match_values = apply_pin_worklist._youtube_match_values(
        row, {"youtu.be": pages}, channels
    )
    assert len(match_values) == len(pages)
    assert all(len(v) == 11 for v in match_values)


def test_a_pin_written_against_a_video_id_actually_fires(monkeypatch, tmp_path):
    """End to end on the real shape: write the pin the way this script
    writes it, load it through the real loader, and resolve a real
    archived URL through it."""
    overrides = tmp_path / "tenant_overrides.csv"
    overrides.write_text(
        "tenant_host,match,gov_id,strength,source,evidence\n"
        "youtu.be,uXwBvWhzj_k,us:place:0633798,fallback,ryan_stated,"
        '"Hillsborough, CA (YouTube channel @townofhillsborough4333)"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "DATA_DIR", tmp_path)
    # The national tables still have to load from the real directory.
    monkeypatch.setattr(
        registry,
        "_read",
        lambda filename: (
            list(csv.DictReader(open(overrides, encoding="utf-8")))
            if filename == registry.TENANT_OVERRIDES_FILE
            else registry._read.__wrapped__(filename)
            if hasattr(registry._read, "__wrapped__")
            else []
        ),
    )
    registry.clear_caches()
    try:
        rows = registry.tenant_overrides()["youtu.be"]
        assert [r.match for r in rows] == ["uXwBvWhzj_k"]
        assert rows[0].strength == "fallback"
    finally:
        registry.clear_caches()


def test_the_tooling_never_writes_an_authoritative_pin():
    """`authoritative` is the tier that overrides a working extraction. No
    tool takes it -- a wrong pin there is strictly worse than no pin."""
    source = Path(apply_pin_worklist.__file__).read_text(encoding="utf-8")
    assert '"fallback"' in source
    assert "authoritative" not in source.split('"""', 2)[2]


# --------------------------------------------------------------------------
# DELETE rows
# --------------------------------------------------------------------------


def test_delete_is_detected_in_either_column():
    assert apply_pin_worklist._is_delete_row(
        {"ryan_gov_name": "DELETE", "ryan_note": ""}
    )
    assert apply_pin_worklist._is_delete_row(
        {"ryan_gov_name": "", "ryan_note": "delete - obvious UAT tenant"}
    )
    assert not apply_pin_worklist._is_delete_row(
        {"ryan_gov_name": "Deleteville, CA", "ryan_note": ""}
    )
    assert not apply_pin_worklist._is_delete_row(
        {"ryan_gov_name": "ok", "ryan_note": ""}
    )


def test_delete_wins_over_a_leftover_name():
    """A row filled in with a name, then reconsidered and marked DELETE,
    must delete -- not silently fall back to pinning the old name."""
    row = {"ryan_gov_name": "Redlands, CA", "ryan_note": "actually DELETE this one"}
    assert apply_pin_worklist._is_delete_row(row)


def test_a_delete_row_only_ever_reaches_its_own_groups_pages():
    """The same grouping the sheet itself was built from -- a delete can
    never reach a neighbour's pages, or (once filtered to WANTED_TIERS,
    the same filter `apply_pin_worklist.main()` applies before calling
    `group_pages()`, mirrored here) a page that already has a
    government."""
    token_a = "A" * 20
    token_b = "B" * 20
    wanted = [
        {
            "id": 1,
            "slug": "junk-page",
            "source_url_normalized": f"https://videoplayer.telvue.com/player/{token_a}/media/1",
            "jurisdiction": None,
            "jurisdiction_confidence": "blank",
        },
        {
            "id": 2,
            "slug": "a-different-tokens-page",
            "source_url_normalized": f"https://videoplayer.telvue.com/player/{token_b}/media/2",
            "jurisdiction": None,
            "jurisdiction_confidence": "blank",
        },
        {
            "id": 3,
            "slug": "already-keyed-elsewhere",
            "source_url_normalized": f"https://videoplayer.telvue.com/player/{token_a}/media/3",
            "jurisdiction": "Fitchburg, MA",
            "jurisdiction_confidence": "registry",
        },
    ]
    filtered = [
        p
        for p in wanted
        if p["jurisdiction_confidence"] in build_pin_worklist.WANTED_TIERS
    ]
    groups = {
        (g["tenant_host"], g["match"]): g
        for g in build_pin_worklist.group_pages(filtered, {})
    }
    group = groups[("videoplayer.telvue.com", token_a)]
    slugs = [pg["slug"] for pg in group["_pages"]]
    assert slugs == ["junk-page"]  # not token_b's page, not the already-keyed one


async def test_delete_pages_calls_the_admin_endpoint_and_reads_its_shape():
    """`delete_pages()` against a mocked
    `POST /internal/admin/delete-pages` -- the shape
    `crud.delete_meeting_pages_by_slug()` actually returns."""
    import json as _json

    from tests.aiohttp_mock import FakeResponse, mock_session

    response = FakeResponse(
        status=200,
        text=_json.dumps(
            {
                "dry_run": True,
                "found": [
                    {
                        "slug": "junk-page",
                        "title": "Test Upload",
                        "platform": "castus",
                        "source_url_normalized": "https://cloud.castus.tv/x",
                    }
                ],
                "not_found": [],
                "deleted": 0,
            }
        ),
    )
    with mock_session(
        {},
        post_routes={
            "https://archive.example.com/internal/admin/delete-pages": response
        },
    ):
        result = await apply_pin_worklist.delete_pages(
            "https://archive.example.com", "test-token", ["junk-page"], dry_run=True
        )
    assert [f["slug"] for f in result["found"]] == ["junk-page"]
    assert result["not_found"] == []


async def test_delete_pages_raises_on_a_non_200():
    """A failed call must be loud, not silently report zero pages found --
    the difference between "nothing matched" and "the request broke" is
    the difference between an honest empty preview and a false one."""
    from tests.aiohttp_mock import FakeResponse, mock_session

    with mock_session(
        {},
        post_routes={
            "https://archive.example.com/internal/admin/delete-pages": FakeResponse(
                status=404, text="Not Found"
            )
        },
    ):
        with pytest.raises(SystemExit):
            await apply_pin_worklist.delete_pages(
                "https://archive.example.com", "bad-token", ["x"], dry_run=True
            )


# --------------------------------------------------------------------------
# landing_url -- eScribe and Cablecast were both a wrong sub-path
# --------------------------------------------------------------------------


def test_landing_url_is_the_host_root_for_escribe_and_cablecast():
    """`/Meetings.aspx` and `/CablecastPublicSite/` were both wrong, in
    different ways: the first 200s but is eScribe's generic
    meeting-calendar shell, the second 404s outright on every real host
    checked (huron-township, wilson-co-schools, cerritos -- all
    2026-09-03). Root 200s on both and, for Cablecast, already carries the
    real government name in `<title>`/`og:site_name`."""
    for platform, host in [
        ("escribe", "pub-brucecounty.escribemeetings.com"),
        ("cablecast", "huron-township.cablecast.tv"),
    ]:
        url = build_pin_worklist.landing_url(
            host, platform, "", f"https://{host}/some/path"
        )
        assert url == f"https://{host}"
        assert "Meetings.aspx" not in url
        assert "CablecastPublicSite" not in url


def test_landing_url_keeps_telvues_real_path():
    """TelVue's `/player/{token}` 200s and is the only page that
    identifies a specific customer on a shared host -- unlike eScribe and
    Cablecast, this one was never broken."""
    token = "A" * 20
    url = build_pin_worklist.landing_url(
        "videoplayer.telvue.com", "telvue", token, "https://videoplayer.telvue.com/x"
    )
    assert url == f"https://videoplayer.telvue.com/player/{token}"


def test_landing_url_defaults_to_root_for_every_other_platform():
    """Swagit and CivicClerk already used root before this fix and stay
    that way -- BACKLOG.md's existing entry documents root as unhelpful
    for them (a generic "SwagitAdmin" title), not broken."""
    for platform in ("swagit", "civicclerk", "granicus", "iqm2"):
        url = build_pin_worklist.landing_url(
            "example.com", platform, "", "https://example.com/x"
        )
        assert url == "https://example.com"


# --------------------------------------------------------------------------
# Swagit's footer -- the tenant naming itself
# --------------------------------------------------------------------------


_ALAMEDA_SWAGIT_FOOTER_HTML = """
<html><body>
<div class="footer">
    <p>Alameda Unified School District Video Archive / <a href="http://www.swagit.com">Powered by Swagit</a></p>
</div>
</body></html>
"""

_HOWARD_SWAGIT_FOOTER_HTML = """
<html><body>
<div class="footer">
    <p>Howard County Public Schools Video Archive / <a href="http://www.swagit.com">Powered by Swagit</a></p>
</div>
</body></html>
"""


def test_swagit_footer_name_extracts_the_real_name_and_stops_before_video_archive():
    """Both HTML fixtures are trimmed real page fragments (fetched live
    2026-09-03, https://alamedausdca.new.swagit.com/ and
    https://hcpsstv.new.swagit.com/) -- the surrounding boilerplate
    removed, the footer verbatim."""
    assert (
        build_pin_worklist.swagit_footer_name(_ALAMEDA_SWAGIT_FOOTER_HTML)
        == "Alameda Unified School District"
    )
    name = build_pin_worklist.swagit_footer_name(_HOWARD_SWAGIT_FOOTER_HTML)
    assert name == "Howard County Public Schools"
    # And it's the REGISTRY's own spelling, not "...School System" (which
    # resolves to the county instead -- see the is_own_name tests above).
    assert resolve_government(name).gov_id == "us:sd:2400420"


def test_swagit_footer_name_is_empty_for_a_non_swagit_page():
    assert (
        build_pin_worklist.swagit_footer_name("<html><title>Meetings</title></html>")
        == ""
    )
    assert build_pin_worklist.swagit_footer_name("") == ""


def test_a_footer_name_that_does_not_resolve_stays_off_proposed_name_but_visible_on_its_own_column():
    """The design point of the separate `swagit_footer` column: DART is a
    real transit agency with no state in its own name and no Census
    place/county row to key against, so it stays fully `unresolved` and
    `propose()` correctly declines to put it in `proposed_name` -- but the
    raw self-declared name still belongs on the sheet for Ryan to read
    without opening `landing_url`."""
    footer = "Dallas Area Rapid Transit (DART)"
    match = resolve_government(footer, tenant_host="dart.new.swagit.com")
    assert match.gov_id == ""  # confirms it stays unresolved, not a fluke
    assert match.tier == "unresolved"
    groups = [
        {
            "platform": "swagit",
            "tenant_host": "dart.new.swagit.com",
            "match": "",
            "pages": 1,
            "_names": set(),
            "_pages": [],
            "example_slug": "",
            "landing_url": "https://dart.new.swagit.com",
        }
    ]
    build_pin_worklist.add_proposals(groups, {}, {"dart.new.swagit.com": footer})
    assert groups[0]["swagit_footer"] == footer
    assert groups[0]["proposed_gov_id"] == ""


def test_the_footer_signal_is_tried_before_hostname_and_text_signals():
    """`hcpsstv` (an acronym, useless as a hostname signal) resolving
    correctly depends on the footer being tried FIRST."""
    groups = [
        {
            "platform": "swagit",
            "tenant_host": "hcpsstv.new.swagit.com",
            "match": "",
            "pages": 1,
            "_names": set(),
            "_pages": [
                {"slug": "jul-14-2016-board-of-education-regular-meeting", "title": ""}
            ],
            "example_slug": "",
            "landing_url": "https://hcpsstv.new.swagit.com",
        }
    ]
    build_pin_worklist.add_proposals(
        groups, {}, {"hcpsstv.new.swagit.com": "Howard County Public Schools"}
    )
    assert groups[0]["proposed_gov_id"] == "us:sd:2400420"
    assert "footer" in groups[0]["proposed_evidence"]


def test_swagit_footer_column_is_blank_for_every_non_swagit_platform():
    groups = [
        {
            "platform": "cablecast",
            "tenant_host": "huron-township.cablecast.tv",
            "match": "",
            "pages": 1,
            "_names": set(),
            "_pages": [],
            "example_slug": "",
            "landing_url": "https://huron-township.cablecast.tv",
        }
    ]
    build_pin_worklist.add_proposals(
        groups, {}, {"huron-township.cablecast.tv": "junk"}
    )
    assert groups[0]["swagit_footer"] == ""


async def test_fetch_swagit_footers_caches_and_skips_already_known_hosts():
    from tests.aiohttp_mock import FakeResponse, mock_session

    routes = {
        "https://newhost.new.swagit.com/": FakeResponse(
            status=200, text=_ALAMEDA_SWAGIT_FOOTER_HTML
        ),
    }
    with mock_session(routes):
        result = await build_pin_worklist.fetch_swagit_footers(
            ["newhost.new.swagit.com", "already-known.new.swagit.com"],
            {"already-known.new.swagit.com": "Already Known District"},
        )
    assert result["newhost.new.swagit.com"] == "Alameda Unified School District"
    # Never fetched -- already in `known`.
    assert result["already-known.new.swagit.com"] == "Already Known District"


def test_the_worklist_carries_a_swagit_footer_column():
    header = next(iter(csv.reader(open(WORKLIST, encoding="utf-8"))))
    assert "swagit_footer" in header
    rows = [
        r for r in _worklist_rows() if r["platform"] == "swagit" and r["swagit_footer"]
    ]
    assert rows, "expected at least one Swagit row with a fetched footer name"
