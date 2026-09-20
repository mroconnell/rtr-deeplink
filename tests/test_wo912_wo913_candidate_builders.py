"""WO-912/WO-913 (2026-09-20): unit coverage for the two candidate builders
(`scripts/wo912_build_candidates.py`, `scripts/wo913_build_candidates.py`)
and the pure logic in `scripts/wo912_headless_second_opinion.py`.

Per this repo's synthetic-test rule, the CSV files each test builds are
hand-made (SYNTHETIC) -- the real ones live in `~/Documents/rtr-business/`,
which CI cannot see -- but every government in them is a REAL row copied
verbatim from the live research file / registry on 2026-09-20, so each
filter branch is exercised with a fact that can be re-checked there:

* Woodbury town, TN (`us:place:4781560`) -- a real WO-912 candidate.
* Albertville City School District, AL (`us:sd:0100005`, reject
  `no-platform-signature`) -- a real school district the filter must drop.
* Oklahoma (`us:state:40`) -- one of the two real state rows.
* Trafford town, AL (`us:place:0176680`) -- a real row whose recorded hub is
  a YouTube embed (never fetched directly, per CLAUDE.md).
* Valley Head town, AL (`us:place:0178240`) -- a real row with a blank domain.
* Arab city, AL (`us:place:0102116`) -- a real government WO-148 already
  ran through the headless rung (its `wo148_report.csv` row says so).
* San Fernando city, CA (`us:place:0666140`) -- rejected, but already has an
  Archive page.
* Pierce County WA, Hialeah FL, Hoover AL, Jackson County AL and Perdido
  Beach AL -- the real bare-`/AgendaCenter` and near-miss hubs the WO-913
  builder must classify (hub URLs verbatim from the research file).

`classify()`'s "found" case uses a REAL captured page,
`tests/fixtures/wo228_hub_ranking/zoar_youtube_home.html` (Zoar village
OH); its challenge/error/no-link cases are minimal hand-built strings, since
a challenge page or a launch error has no real captured fixture in this
repo -- the "Just a moment" text is the real Cloudflare marker in
`CHALLENGE_MARKERS`, and the certificate error text is the real one WO-909
recorded in a proxied sandbox.
"""

import csv
import os

import pytest

import scripts.wo912_build_candidates as b912
import scripts.wo913_build_candidates as b913
import scripts.wo912_wo913_make_leads as leads
import scripts.wo912_wo913_ingest_confirmed as ingest
from scripts.wo912_headless_second_opinion import classify, qualifies

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wo228_hub_ranking")


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# --- wo912_build_candidates ------------------------------------------------


@pytest.mark.parametrize(
    "pop,band",
    [
        (None, "population blank"),
        (0, "under 1,000"),
        (999, "under 1,000"),
        (1000, "1,000-2,499"),
        (2499, "1,000-2,499"),
        (2500, "2,500-4,999"),
        (4999, "2,500-4,999"),
        (5000, "5,000-9,999"),
        (9999, "5,000-9,999"),
        (10000, "10,000+"),
        (941170, "10,000+"),
    ],
)
def test_pop_band_boundaries(pop, band):
    assert b912.pop_band(pop) == band


def test_first_takes_the_first_non_blank_value_across_rows():
    rows = [{"domain": ""}, {"domain": "  "}, {"domain": "a.gov"}, {"domain": "b.gov"}]
    assert b912.first(rows, "domain") == "a.gov"
    assert b912.first(rows, "missing_column") == ""


def test_rank_sample_depends_only_on_seed_and_the_set_of_rows():
    ids = [f"us:place:{n:07d}" for n in range(40)]
    fwd = b912.rank_sample([{"gov_id": g} for g in ids], 912)
    rev = b912.rank_sample([{"gov_id": g} for g in reversed(ids)], 912)
    assert [r["gov_id"] for r in fwd] == [r["gov_id"] for r in rev]
    assert [r["sample_rank"] for r in fwd] == list(range(1, 41))
    other = b912.rank_sample([{"gov_id": g} for g in ids], 7)
    assert [r["gov_id"] for r in other] != [r["gov_id"] for r in fwd]


def _wo912_files(tmp_path):
    reg_header = [
        "gov_id",
        "name",
        "state",
        "country",
        "gov_kind",
        "population",
        "archive_pages",
    ]
    _write_csv(
        tmp_path / "registry.csv",
        reg_header,
        [
            [
                "us:place:4781560",
                "Woodbury town",
                "TN",
                "us",
                "municipality",
                "2831",
                "0",
            ],
            [
                "us:sd:0100005",
                "Albertville City School District",
                "AL",
                "us",
                "school_district",
                "",
                "0",
            ],
            ["us:state:40", "Oklahoma", "OK", "us", "state", "", "0"],
            [
                "us:place:0176680",
                "Trafford town",
                "AL",
                "us",
                "municipality",
                "599",
                "0",
            ],
            [
                "us:place:0178240",
                "Valley Head town",
                "AL",
                "us",
                "municipality",
                "595",
                "0",
            ],
            ["us:place:0102116", "Arab city", "AL", "us", "municipality", "8918", "0"],
            [
                "us:place:0666140",
                "San Fernando city",
                "CA",
                "us",
                "municipality",
                "23488",
                "1",
            ],
        ],
    )
    jc_header = [
        "gov_id",
        "domain",
        "reject_reason",
        "transcribed",
        "example_agenda_or_calendar_url",
        "example_meeting_url",
    ]
    nplf = "no-platform-link-found"
    _write_csv(
        tmp_path / "jc.csv",
        jc_header,
        [
            ["us:place:4781560", "villageofwoodbury.gov", nplf, "", "", ""],
            ["us:sd:0100005", "albertk12.org", "no-platform-signature", "", "", ""],
            ["us:state:40", "oklahoma.gov", nplf, "", "", ""],
            [
                "us:place:0176680",
                "traffordal.gov",
                nplf,
                "",
                "https://www.youtube.com/embed/reuuCPE3lZw",
                "",
            ],
            ["us:place:0178240", "", nplf, "", "", ""],
            ["us:place:0102116", "arabcity.org", nplf, "", "", ""],
            ["us:place:0666140", "sanfernando.gov", nplf, "", "", ""],
        ],
    )
    # Arab city really did reach a headless rung in WO-148's report; Woodbury
    # appears in another ladder report but only ever reached `plain`, which
    # must NOT count as having been headless-checked.
    _write_csv(
        tmp_path / "wo148_report.csv",
        ["gov_id", "rung_answered"],
        [["us:place:0102116", "headless"], ["us:place:4781560", "plain"]],
    )
    # A CSV with no rung column at all is ignored, not an error.
    _write_csv(tmp_path / "wo999_notes.csv", ["gov_id", "note"], [["x", "y"]])


def _patch_wo912(monkeypatch, tmp_path):
    monkeypatch.setattr(b912, "RESEARCH_DIR", tmp_path)
    monkeypatch.setattr(b912, "JC_CSV", tmp_path / "jc.csv")
    monkeypatch.setattr(b912, "REGISTRY_CSV", tmp_path / "registry.csv")


def test_wo912_build_applies_every_filter(tmp_path, monkeypatch):
    _wo912_files(tmp_path)
    _patch_wo912(monkeypatch, tmp_path)

    kept, drops = b912.build(seed=912, include_checked=False)

    assert [r["gov_id"] for r in kept] == ["us:place:4781560"]
    only = kept[0]
    assert only["name"] == "Woodbury town"
    assert only["population"] == "2831"
    assert only["pop_band"] == "2,500-4,999"
    assert only["domain"] == "villageofwoodbury.gov"
    assert only["sample_rank"] == 1
    assert drops["kind school_district"] == 1
    assert drops["kind state"] == 1
    assert drops["youtube url on the row"] == 1
    assert drops["blank domain"] == 1
    assert drops["already reached a headless rung"] == 1
    assert drops["already has an Archive page"] == 1


def test_wo912_include_checked_keeps_the_headless_reached_government(
    tmp_path, monkeypatch
):
    _wo912_files(tmp_path)
    _patch_wo912(monkeypatch, tmp_path)

    kept, _ = b912.build(seed=912, include_checked=True)

    assert {r["gov_id"] for r in kept} == {"us:place:4781560", "us:place:0102116"}


# --- wo913_build_candidates ------------------------------------------------


@pytest.mark.parametrize(
    "hub,expected",
    [
        ("https://piercecountywa.gov/AgendaCenter", True),
        ("http://hooveral.gov/AgendaCenter", True),
        # Trailing slash / lower case / no scheme: same empty shell, other
        # spellings (hosts are real; only the spelling is varied).
        ("https://jacksoncountyal.gov/AgendaCenter/", True),
        ("https://www.hialeahfl.gov/agendacenter", True),
        ("www.hialeahfl.gov/AgendaCenter", True),
        # Not the empty shell: a search/file page, a query, a fragment on
        # another page (the real Perdido Beach shape), or nothing at all.
        ("http://hooveral.gov/AgendaCenter/Search/?term=&CIDs=all", False),
        ("https://piercecountywa.gov/AgendaCenter?x=1", False),
        ("https://www.townofperdidobeach.org/list.aspx#agendaCenter", False),
        ("", False),
    ],
)
def test_is_bare_agendacenter(hub, expected):
    assert b913.is_bare_agendacenter(hub) is expected


def test_wo913_build_keeps_rejected_no_page_bare_hubs_biggest_first(
    tmp_path, monkeypatch
):
    reg_header = [
        "gov_id",
        "name",
        "state",
        "country",
        "gov_kind",
        "population",
        "archive_pages",
    ]
    _write_csv(
        tmp_path / "registry.csv",
        reg_header,
        [
            [
                "us:place:1230000",
                "Hialeah city",
                "FL",
                "us",
                "municipality",
                "235388",
                "0",
            ],
            ["us:county:53053", "Pierce County", "WA", "us", "county", "941170", "0"],
            [
                "us:place:0135896",
                "Hoover city",
                "AL",
                "us",
                "municipality",
                "93013",
                "1",
            ],
            ["us:county:01071", "Jackson County", "AL", "us", "county", "53780", "1"],
            [
                "us:place:0159088",
                "Perdido Beach town",
                "AL",
                "us",
                "municipality",
                "584",
                "0",
            ],
        ],
    )
    jc_header = [
        "gov_id",
        "domain",
        "reject_reason",
        "transcribed",
        "example_agenda_or_calendar_url",
    ]
    _write_csv(
        tmp_path / "jc.csv",
        jc_header,
        [
            [
                "us:place:1230000",
                "hialeahfl.gov",
                "meeting-without-video",
                "",
                "https://www.hialeahfl.gov/AgendaCenter",
            ],
            [
                "us:county:53053",
                "piercecountywa.gov",
                "video-no-captions-queued",
                "",
                "https://piercecountywa.gov/AgendaCenter",
            ],
            # Bare hub, rejected, but already on the site.
            [
                "us:place:0135896",
                "hooveral.gov",
                "video-no-captions-queued",
                "",
                "http://hooveral.gov/AgendaCenter",
            ],
            # Bare hub but ingested (transcribed set, no reject reason).
            [
                "us:county:01071",
                "jacksoncountyal.gov",
                "",
                "yes",
                "https://jacksoncountyal.gov/AgendaCenter",
            ],
            # Rejected, but not the bare shell.
            [
                "us:place:0159088",
                "townofperdidobeach.org",
                "no-platform-link-found",
                "",
                "https://www.townofperdidobeach.org/list.aspx#agendaCenter",
            ],
        ],
    )
    monkeypatch.setattr(b913, "JC_CSV", tmp_path / "jc.csv")
    monkeypatch.setattr(b913, "REGISTRY_CSV", tmp_path / "registry.csv")

    kept, tally = b913.build()

    assert [r["gov_id"] for r in kept] == ["us:county:53053", "us:place:1230000"]
    assert kept[0]["hub_url"] == "https://piercecountywa.gov/AgendaCenter"
    assert kept[0]["domain"] == "piercecountywa.gov"
    assert tally["bare /AgendaCenter hub"] == 4
    assert tally["already has an Archive page"] == 1
    assert tally["not rejected (ingested or untested)"] == 1


# --- wo912_headless_second_opinion -----------------------------------------

_NO_HIT_NOTE = "reached, hop links checked, no platform link found"


def _report_row(**overrides):
    row = {
        "exception": "",
        "rung_answered": "plain",
        "platform": "",
        "note": _NO_HIT_NOTE,
        "final_url": "https://villageofwoodbury.gov/",
    }
    row.update(overrides)
    return row


def test_qualifies_only_for_plain_reached_hop_links_checked_nothing_found():
    assert qualifies(_report_row())


@pytest.mark.parametrize(
    "overrides",
    [
        # The ladder already sent it to headless, and headless found nothing.
        {
            "rung_answered": "headless",
            "note": "headless reached the page, no platform link found",
        },
        # The ladder tried headless and it failed (the real WO-909 sandbox error).
        {"note": "headless failed: Error: Page.goto: net::ERR_CERT_AUTHORITY_INVALID"},
        # A WAF-blocked plain fetch: never sent to headless, by the ladder's own rule.
        {"rung_answered": "browser-headers"},
        {"rung_answered": "challenge", "note": ""},
        {"rung_answered": "dead", "note": "dns-fail on https://www.example.invalid"},
        # Already found something.
        {"platform": "youtube"},
        # A Python exception escaped the ladder for this row.
        {"exception": "TimeoutError: boom"},
        # Nothing to re-render.
        {"final_url": ""},
        # CLAUDE.md: youtube.com / youtu.be are never fetched from this Mac,
        # not even by a browser -- refused whether the pilot's own audit
        # column says so or only the URL does.
        {"final_url_is_youtube": "True"},
        {"final_url": "https://www.youtube.com/@TownofWoodside"},
        {"final_url": "https://youtu.be/5LZqoNDRMYk"},
    ],
)
def test_qualifies_rejects_everything_else(overrides):
    assert not qualifies(_report_row(**overrides))


def test_classify_finds_a_real_youtube_link_in_a_real_rendered_page():
    with open(
        os.path.join(FIXTURE_DIR, "zoar_youtube_home.html"),
        encoding="utf-8",
        errors="replace",
    ) as f:
        html = f.read()
    out = classify(
        html, "https://historiczoarvillage.com/", None, "historiczoarvillage.com"
    )
    assert out["second_opinion"] == "found"
    assert out["platform"] == "youtube"
    assert "youtube.com" in out["hit_url"] or "youtu.be" in out["hit_url"]


def test_classify_stops_at_a_human_verification_page():
    out = classify(
        "<html><title>Just a moment...</title></html>", "https://x.gov/", None, "x.gov"
    )
    assert out["second_opinion"] == "challenge"
    assert out["platform"] == ""


def test_classify_records_a_headless_failure_as_an_error_not_a_miss():
    out = classify(
        None, "https://x.gov/", "Error: net::ERR_CERT_AUTHORITY_INVALID", "x.gov"
    )
    assert out["second_opinion"] == "error"
    assert "ERR_CERT_AUTHORITY_INVALID" in out["error"]


def test_classify_reports_none_when_the_rendered_page_has_no_platform_link():
    out = classify(
        "<html><body><a href='/about'>About</a></body></html>",
        "https://x.gov/",
        None,
        "x.gov",
    )
    assert out["second_opinion"] == "none"


def test_classify_rejects_the_real_dubois_wy_direct_file_false_positive():
    # The real WO-908 false positive: Dubois town, WY's homepage links out
    # to the National Park Service, and a Yellowstone orientation .mp4 there
    # matches `direct_file` by extension alone. Same guard as the pilot's.
    nps = (
        "https://www.nps.gov/nps-audiovideo/legacy/yell/"
        "A35E7E79-CDF6-74D8-26332556B9F2D5E2/"
        "yell-Orientationnocaptions2_1280x720.mp4"
    )
    html = f'<html><body><a href="{nps}">Watch</a></body></html>'
    out = classify(html, "https://www.duboiswyoming.org/", None, "duboiswyoming.org")
    assert out["second_opinion"] == "none"
    assert out["direct_file_plausible"] == "False"


# --- wo912_wo913_make_leads ----------------------------------------------------
# Every URL below is a real one from the WO-912/WO-913 hand-checks.


@pytest.mark.parametrize(
    "url,kind,key,clean",
    [
        (
            "https://www.youtube.com/channel/UCz9BIrtFrr3-YfuIbfS2SQA?view_as=subscriber",
            "channel",
            "channel/UCz9BIrtFrr3-YfuIbfS2SQA",
            "https://www.youtube.com/channel/UCz9BIrtFrr3-YfuIbfS2SQA",
        ),
        (
            "http://www.youtube.com/@CityofPassaicNJ",
            "channel",
            "@cityofpassaicnj",
            "https://www.youtube.com/@CityofPassaicNJ",
        ),
        (
            "https://www.youtube.com/@townofjunobeach477/streams",
            "channel",
            "@townofjunobeach477",
            "https://www.youtube.com/@townofjunobeach477",
        ),
        (
            "https://www.youtube.com/user/piercecountytv",
            "channel",
            "user/piercecountytv",
            "https://www.youtube.com/user/piercecountytv",
        ),
        (
            "https://www.youtube.com/c/CityofGlenwoodSprings",
            "channel",
            "c/cityofglenwoodsprings",
            "https://www.youtube.com/c/CityofGlenwoodSprings",
        ),
        # A real row carried a trailing space: youtube.com/cityofmccall<space>
        (
            "https://www.youtube.com/cityofmccall ",
            "channel",
            "c/cityofmccall",
            "https://www.youtube.com/cityofmccall",
        ),
        (
            "http://www.youtube.com/watch?v=fUO_lpree8A&feature=youtu.be",
            "single_video",
            "video/fUO_lpree8A",
            "https://www.youtube.com/watch?v=fUO_lpree8A",
        ),
        (
            "https://www.youtube.com/embed/eV138uM1h-w?rel=0",
            "single_video",
            "video/eV138uM1h-w",
            "https://www.youtube.com/watch?v=eV138uM1h-w",
        ),
        (
            "https://youtu.be/jV4-JywwKI0",
            "single_video",
            "video/jV4-JywwKI0",
            "https://www.youtube.com/watch?v=jV4-JywwKI0",
        ),
        (
            "https://m.youtube.com/watch?v=RKnw_ibS7tM",
            "single_video",
            "video/RKnw_ibS7tM",
            "https://www.youtube.com/watch?v=RKnw_ibS7tM",
        ),
    ],
)
def test_normalise_youtube_url(url, kind, key, clean):
    assert leads.normalise_youtube_url(url) == (kind, key, clean)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com",  # bare home page (Cairo NE, Marion County OH)
        "https://youtube.com/",  # bare (Charlotte TN)
        # a Google sign-in page (Murtaugh ID), not a channel
        "https://accounts.youtube.com/accounts/CheckConnection?pmpo=https://accounts.google.com",
        # an embed with no video id (Arabi GA's drone-footage embed)
        "https://www.youtube.com/embed/?modestbranding=1&autoplay=0",
        "https://www.youtube.com/results?search_query=council+meeting",
        "https://vimeo.com/567504506",
        "https://play.champds.com/broadviewheightsoh/event/315",
        "",
    ],
)
def test_normalise_youtube_url_rejects_what_is_not_a_channel_or_video(url):
    assert leads.normalise_youtube_url(url) is None


def test_same_channel_in_two_spellings_is_one_lead_and_head_wins(monkeypatch):
    head = [
        # already in the committed file, under the other spelling of the handle
        {
            "channel_url": "https://www.youtube.com/@cityofmonroenc",
            "gov_id": "us:place:3743920",
        },
    ]
    cands = [
        {
            "url": "https://www.youtube.com/@CityOfMonroeNC",
            "gov_id": "us:place:3743920",
            "name": "Monroe city",
            "note": "handle names the city",
        },
        {
            "url": "https://www.youtube.com/@townofpittsboronc",
            "gov_id": "us:place:3752660",
            "name": "Pittsboro town",
            "note": "AgendaCenter shortcut",
        },
        # the same new channel offered twice must be kept once
        {
            "url": "https://www.youtube.com/@TownofPittsboroNC/streams",
            "gov_id": "us:place:3752660",
            "name": "Pittsboro town",
            "note": "AgendaCenter shortcut",
        },
        {
            "url": "http://www.youtube.com",
            "gov_id": "us:place:3107625",
            "name": "Cairo village",
            "note": "bare home page",
        },
    ]
    monkeypatch.setattr(leads, "candidate_leads", lambda wo: cands)
    kept, tally = leads.build("wo913", head, {"us:place:3752660": "North Carolina"})
    assert [r["channel_url"] for r in kept] == [
        "https://www.youtube.com/@townofpittsboronc"
    ]
    assert kept[0]["state"] == "North Carolina"
    assert kept[0]["source_wo"] == "WO-913"
    assert kept[0]["verified"] == "false"
    assert tally["already listed"] == 2
    assert tally["not a channel or video URL"] == 1


# --- wo912_wo913_ingest_confirmed -----------------------------------------------


def test_civicclerk_hit_gets_its_tenant_root_added_for_the_depth_search():
    urls = ingest.hit_source_urls_for(
        "civicclerk", "https://toledoor.portal.civicclerk.com/event/104/media"
    )
    assert urls == (
        "civicclerk=https://toledoor.portal.civicclerk.com/event/104/media;"
        "civicclerk=https://toledoor.portal.civicclerk.com"
    )


def test_other_platform_hits_are_passed_through_unchanged():
    assert (
        ingest.hit_source_urls_for(
            "champds", "https://play.champds.com/broadviewheightsoh/event/315"
        )
        == "champds=https://play.champds.com/broadviewheightsoh/event/315"
    )
    assert ingest.civicclerk_tenant_root("https://example.com/event/1") == ""


async def test_configure_installs_the_identity_hook_and_records_youtube_refusals(
    tmp_path, monkeypatch
):
    """The ingest wrapper's wiring, without a real ingest. Two facts matter:
    WO-134's identity/jurisdiction hook is installed (it defaults to None, and
    the Archive trusts a caller-supplied gov_id, so without it a row whose
    recorded domain is another government's is filed under the wrong one), and
    a row on which the YouTube guard fired is written down rather than lost."""
    from types import SimpleNamespace

    monkeypatch.setattr(ingest, "REFUSED_CSV", tmp_path / "refused.csv")
    seen = []

    async def fake_process_row(session, row, covered, source_tag):
        seen.append(row["gov_id"])
        refused.append("www.youtube.com")  # what the guard records on a refusal
        return "result"

    fake_w134 = SimpleNamespace(
        process_row=fake_process_row,
        JURISDICTION_CHECK_HOOK=None,
        # what importing wo149_county_ladder_sweep leaves behind on the module
        TIER3_HANDLER=lambda **kwargs: None,
        INPUT_CSVS=None,
        LOG_CSV=None,
    )
    refused: list[str] = []

    def hook(result, gov_id, unit_name, platform, final_seed):
        return True, ""

    ingest.configure(fake_w134, hook, refused)

    assert fake_w134.JURISDICTION_CHECK_HOOK is hook
    # Not another sweep's shared pending file: WO-134's direct tier-3 path.
    assert fake_w134.TIER3_HANDLER is None
    assert fake_w134.INPUT_CSVS == [ingest.INPUT_CSV]
    assert fake_w134.LOG_CSV == ingest.LOG_CSV

    row = {
        "gov_id": "us:place:4174000",
        "unit_name": "Toledo city",
        "platform_hits": "civicclerk",
        "hit_source_urls": "civicclerk=https://toledoor.portal.civicclerk.com/event/104/media",
    }
    assert await fake_w134.process_row(None, row, set(), "wo913") == "result"
    assert seen == ["us:place:4174000"]
    logged = list(csv.DictReader(open(tmp_path / "refused.csv", newline="")))
    assert [(r["gov_id"], r["hosts_refused"]) for r in logged] == [
        ("us:place:4174000", "www.youtube.com")
    ]


def test_build_input_never_sends_a_youtube_row_to_the_ingest_path(
    tmp_path, monkeypatch
):
    hc_header = [
        "gov_id",
        "name",
        "state",
        "platform",
        "hit_url",
        "source_step",
        "verdict",
        "action",
        "basis",
    ]
    _write_csv(
        tmp_path / "wo913_handcheck.csv",
        hc_header,
        [
            # a YouTube row wrongly marked action=ingest must still be skipped
            [
                "us:place:3743920",
                "Monroe city",
                "NC",
                "youtube",
                "https://www.youtube.com/@cityofmonroenc",
                "x",
                "right_gov",
                "ingest",
                "b",
            ],
            [
                "us:place:4174000",
                "Toledo city",
                "OR",
                "civicclerk",
                "https://toledoor.portal.civicclerk.com/event/104/media",
                "x",
                "right_meeting",
                "ingest",
                "b",
            ],
        ],
    )
    _write_csv(
        tmp_path / "wo913_report.csv",
        ["gov_id", "domain", "population"],
        [["us:place:4174000", "cityoftoledo.org", "3514"]],
    )
    monkeypatch.setattr(
        ingest, "HANDCHECKS", [(tmp_path / "wo913_handcheck.csv", "wo913")]
    )
    monkeypatch.setattr(ingest, "REPORTS", {"wo913": tmp_path / "wo913_report.csv"})

    rows = ingest.build_input()

    assert [r["gov_id"] for r in rows] == ["us:place:4174000"]
    assert rows[0]["homepage"] == "https://cityoftoledo.org"


def test_a_manual_playlist_lead_is_kept_as_a_playlist_and_deduped_on_its_list_id(
    monkeypatch,
):
    # Warren County IA's home page links a meetings PLAYLIST (a real find).
    url = "https://www.youtube.com/playlist?list=PL0wekmYzETMdNIqP_h5XFplmgZl65iqtw"
    cands = [
        {
            "url": url,
            "gov_id": "us:county:19181",
            "name": "Warren County",
            "note": "VIEW MEETINGS",
            "kind": "playlist",
        },
        {
            "url": url + "&si=x",
            "gov_id": "us:county:19181",
            "name": "Warren County",
            "note": "same list, other spelling",
            "kind": "playlist",
        },
    ]
    monkeypatch.setattr(leads, "candidate_leads", lambda wo: cands)

    kept, tally = leads.build("wo912", [], {"us:county:19181": "Iowa"})

    assert [(r["kind"], r["channel_url"]) for r in kept] == [("playlist", url)]
    assert tally["already listed"] == 1


def test_the_two_vimeo_pins_this_wo_committed_match_their_real_urls():
    """WO-134's pin writer emits `vimeo:<id>`, which a real Vimeo path never
    contains, so such a pin silently never applies (`BACKLOG_DONE.md`, WO-924,
    which later made the loader refuse that shape). The two rows this WO
    committed were rewritten by hand to the bare-id shape, and each is on the
    host its own page's source URL uses. Without a matching pin the queue's
    owner check refuses a Vimeo line (it would ingest as
    `rtr:unknown:vimeo.com`), so Vienna township's queue line would have
    stalled. Reads the real committed pin file on purpose."""
    from app.platforms.queue_probe import has_owner

    # the queue line as appended to scripts/tier3_auto_transcription_queue.txt
    assert has_owner("https://vimeo.com/195536478") == (
        True,
        "us:cousub:2604982380",
        "",
    )
    # the source URL the Sealy TX page was ingested with
    assert has_owner("https://player.vimeo.com/video/1227954162?h=2ed4198897") == (
        True,
        "us:place:4866464",
        "",
    )
