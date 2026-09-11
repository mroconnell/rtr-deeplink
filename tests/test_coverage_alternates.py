"""Tests for scripts/coverage_alternates.py (WO-181, 2026-09-10).

Rows are hand-built (SYNTHETIC -- no live HTTP happens in this file), but
every name/domain used is a real row from
`~/Documents/rtr-business/research/jurisdiction_coverage.csv` as of
2026-09-10, not an invented government, per CLAUDE.md's rule that a
synthetic test's facts must be independently verifiable even when the
page/response is hand-built:

- Athens city, AL: `domain` athensal.us, `alternate_domains`
  athensalabama.us, `reject_reason` dns-unresolvable (an ACCESS-class
  reject -- the case this WO's alternates retry is for).
- Ashland town, AL: `domain` cityofashland.net, `alternate_domains`
  cityofashlandal.com, `reject_reason` no-platform-link-found (a
  CONTENT-class reject -- the case this WO's scope explicitly does NOT
  retry against an alternate).
- Calera city, AL: `domain` cityofcalera.org, `alternate_domains`
  caleraal.portal.civicclerk.com, `alternate_urls`
  https://caleraal.portal.civicclerk.com/event/803/media -- same host on
  both columns, used to check `candidate_domains()` dedupes it to one
  entry rather than trying it twice.
"""

from __future__ import annotations

import pytest

from scripts.coverage_alternates import (
    ACCESS_REASONS,
    CONTENT_REASONS,
    FOUND,
    MEETING_FOUND_NO_VIDEO_REASONS,
    NEVER_RETRY_REASONS,
    NO_MEETING_CONTENT_REASONS,
    AlternatesResult,
    LadderOutcome,
    already_has_coverage,
    apply_promotion,
    candidate_domains,
    canonicalize_domain,
    classify_domain_shape,
    classify_wo147_ladder_result,
    decide_promotion,
    is_retry_worthy,
    ladder_with_alternates,
    normalize_host,
    one_hop_alternate,
)


def test_normalize_host_strips_scheme_path_port_and_userinfo():
    assert normalize_host("athensal.us") == "athensal.us"
    assert normalize_host("https://athensal.us/") == "athensal.us"
    assert normalize_host("http://www.athensal.us/agendas/") == "www.athensal.us"
    assert normalize_host("https://user:pass@athensal.us:8443/x") == "athensal.us"
    assert normalize_host("") == ""
    assert normalize_host(None) == ""
    # a leading www. is a distinct candidate, not stripped -- the ladder
    # itself tries the www/non-www variant of whatever it's given.
    assert normalize_host("www.athensal.us") == "www.athensal.us"


def test_candidate_domains_orders_primary_then_alternates_then_alt_url_hosts():
    row = {
        "domain": "cityofcalera.org",
        "alternate_domains": "caleraal.portal.civicclerk.com",
        "alternate_urls": "https://caleraal.portal.civicclerk.com/event/803/media",
    }
    # the alternate_urls host is the SAME as the alternate_domains entry
    # -- deduped to one candidate, not tried twice.
    assert candidate_domains(row) == [
        "cityofcalera.org",
        "caleraal.portal.civicclerk.com",
    ]


def test_candidate_domains_skips_blanks_and_dedupes():
    row = {
        "domain": "athensal.us",
        "alternate_domains": "athensalabama.us;;athensal.us",
        "alternate_urls": "",
    }
    assert candidate_domains(row) == ["athensal.us", "athensalabama.us"]


def test_candidate_domains_handles_missing_columns():
    assert candidate_domains({}) == []
    assert candidate_domains({"domain": "athensal.us"}) == ["athensal.us"]


def _scripted_ladder_fn(answers):
    """Returns a ladder_fn that returns `answers[domain]` in sequence,
    recording every call for assertions."""
    calls = []

    async def ladder_fn(domain, row):
        calls.append(domain)
        return answers[domain]

    ladder_fn.calls = calls
    return ladder_fn


@pytest.mark.asyncio
async def test_alternate_answers_after_access_reject_on_primary():
    """Athens city, AL shape: primary domain is dns-unresolvable (ACCESS
    class), the alternate domain finds a real platform link. The helper
    should try the alternate and report it as the answering domain."""
    row = {
        "city_name": "Athens city",
        "state_or_province": "Alabama",
        "domain": "athensal.us",
        "alternate_domains": "athensalabama.us",
        "alternate_urls": "",
        "reject_reason": "dns-unresolvable",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "athensal.us": LadderOutcome(reason="dns-unresolvable"),
            "athensalabama.us": LadderOutcome(
                reason=FOUND,
                platform="civicplus",
                hit_url="https://athensalabama.us/agendacenter",
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn)
    assert isinstance(result, AlternatesResult)
    assert result.outcome.reason == FOUND
    assert result.answered_domain == "athensalabama.us"
    assert ladder_fn.calls == ["athensal.us", "athensalabama.us"]
    assert result.alternates_tried == "athensal.us;athensalabama.us"


@pytest.mark.asyncio
async def test_content_reject_on_primary_never_tries_alternate():
    """Ashland town, AL shape: primary is no-platform-link-found (CONTENT
    class). Per WO-181's scope, this must stop at the primary -- the
    alternate is never called, even though one exists."""
    row = {
        "city_name": "Ashland town",
        "state_or_province": "Alabama",
        "domain": "cityofashland.net",
        "alternate_domains": "cityofashlandal.com",
        "alternate_urls": "",
        "reject_reason": "no-platform-link-found",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "cityofashland.net": LadderOutcome(reason="no-platform-link-found"),
            "cityofashlandal.com": LadderOutcome(
                reason=FOUND, platform="civicplus", hit_url="x"
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn)
    assert result.outcome.reason == "no-platform-link-found"
    assert result.answered_domain == "cityofashland.net"
    assert ladder_fn.calls == ["cityofashland.net"]  # alternate never touched


@pytest.mark.asyncio
async def test_every_candidate_access_class_returns_last_tried():
    row = {
        "domain": "athensal.us",
        "alternate_domains": "athensalabama.us",
        "alternate_urls": "",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "athensal.us": LadderOutcome(reason="dns-unresolvable"),
            "athensalabama.us": LadderOutcome(reason="timeout"),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn)
    assert result.outcome.reason == "timeout"
    assert result.answered_domain == "athensalabama.us"
    assert ladder_fn.calls == ["athensal.us", "athensalabama.us"]


@pytest.mark.asyncio
async def test_no_candidate_domains_reports_dns_unresolvable_without_calling_ladder_fn():
    calls = []

    async def ladder_fn(domain, row):
        calls.append(domain)
        return LadderOutcome(reason=FOUND)

    result = await ladder_with_alternates({}, ladder_fn)
    assert result.outcome.reason == "dns-unresolvable"
    assert calls == []


@pytest.mark.asyncio
async def test_max_candidates_caps_the_trail():
    row = {
        "domain": "athensal.us",
        "alternate_domains": "athensalabama.us;a-third-domain.example",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "athensal.us": LadderOutcome(reason="dns-unresolvable"),
            "athensalabama.us": LadderOutcome(reason="timeout"),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn, max_candidates=2)
    assert ladder_fn.calls == ["athensal.us", "athensalabama.us"]
    assert result.outcome.reason == "timeout"


def test_reason_sets_do_not_overlap_and_found_is_in_neither():
    assert ACCESS_REASONS & CONTENT_REASONS == set()
    assert FOUND not in ACCESS_REASONS
    assert FOUND not in CONTENT_REASONS


class _FakeLadderResult:
    def __init__(self, access_mode, platform=None, hit_url=None, note=""):
        self.access_mode = access_mode
        self.platform = platform
        self.hit_url = hit_url
        self.note = note


def test_classify_wo147_ladder_result_found():
    r = _FakeLadderResult(
        "plain", platform="civicplus", hit_url="https://x/AgendaCenter"
    )
    outcome = classify_wo147_ladder_result(r)
    assert outcome.reason == FOUND
    assert outcome.platform == "civicplus"


@pytest.mark.parametrize(
    "access_mode,expected_reason",
    [
        ("dead", "dns-unresolvable"),
        ("challenge", "cloudflare-challenge-blocked"),
        ("blocked-plain-http", "blocked-plain-http"),
        ("blocked-browser-headers", "blocked-browser-headers"),
        ("timeout", "timeout"),
    ],
)
def test_classify_wo147_ladder_result_access_class(access_mode, expected_reason):
    r = _FakeLadderResult(access_mode)
    assert classify_wo147_ladder_result(r).reason == expected_reason


def test_classify_wo147_ladder_result_reached_no_link_is_content_class():
    r = _FakeLadderResult("plain", platform=None, hit_url=None)
    outcome = classify_wo147_ladder_result(r)
    assert outcome.reason == "no-platform-link-found"
    assert outcome.reason in CONTENT_REASONS


# --- WO-184 (2026-09-11): trigger policy, promotion, one_hop_alternate ---
#
# SYNTHETIC (no live HTTP in this file) -- rows below are hand-built, but
# every name/domain/reject_reason/platform is a real row read from
# `~/Documents/rtr-business/research/jurisdiction_coverage.csv` as of
# 2026-09-10/11:
#
# - Albertville city, AL: `domain` cityofalbertvilleal.gov,
#   `alternate_domains` cityofalbertville.com, `reject_reason`
#   no-platform-link-found -- a CONTENT-class "found nothing at all"
#   reject, retry-worthy under Ryan's `trigger="no-meeting"` rule but NOT
#   under WO-181's original `trigger="access"`.
# - Beverly Hills city, CA: `domain` beverlyhills.gov, `alternate_domains`
#   beverlyhills.org, `reject_reason` meeting-without-video,
#   `suspected_meeting_link_provider` granicus -- a real meeting WAS
#   found (without video); never retry-worthy under either trigger, and
#   the population `one_hop_alternate()` (not the main retry) exists for.
# - Adamsville city, AL: `domain` cityofadamsville.gov, `alternate_domains`
#   cityofadamsville.org, `reject_reason` blank (never tested) -- retry-
#   worthy under `trigger="no-meeting"` only.


def test_already_has_coverage_catches_blank_reason_real_success_row():
    """Real, confirmed bug found running WO-184's own first live test
    batch (2026-09-11): Cook County, IL's real row --
    `domain=cook-county.granicus.com`, `transcribed=True`,
    `shares_video=True`, `reject_reason` BLANK -- is indistinguishable
    from a never-tested row by `reject_reason` alone. `is_retry_worthy`
    would say a blank reason is retry-worthy under `trigger="no-meeting"`;
    `already_has_coverage` is the separate, mandatory row-level guard
    that stops it from being re-probed anyway."""
    row = {
        "city_name": "Cook County",
        "state_or_province": "Illinois",
        "domain": "cook-county.granicus.com",
        "alternate_domains": "cookcountyil.gov",
        "reject_reason": "",
        "transcribed": "True",
        "shares_video": "True",
    }
    assert is_retry_worthy(row["reject_reason"], trigger="no-meeting") is True
    assert already_has_coverage(row) is True


def test_already_has_coverage_false_for_a_genuinely_untested_row():
    # Adamsville city, AL shape again -- never tested, no coverage yet.
    row = {
        "domain": "cityofadamsville.gov",
        "reject_reason": "",
        "transcribed": "",
        "shares_video": "",
    }
    assert already_has_coverage(row) is False


@pytest.mark.parametrize(
    "transcribed,shares_video", [("True", ""), ("", "True"), ("True", "True")]
)
def test_already_has_coverage_true_variants(transcribed, shares_video):
    row = {"transcribed": transcribed, "shares_video": shares_video}
    assert already_has_coverage(row) is True


def test_already_has_coverage_case_and_missing_column_tolerant():
    assert already_has_coverage({"transcribed": "true"}) is True
    assert (
        already_has_coverage({"transcribed": "False", "shares_video": "False"}) is False
    )
    assert already_has_coverage({}) is False


def test_reason_set_membership_is_disjoint_and_matches_ryans_rule():
    # NEVER_RETRY_REASONS is a superset of MEETING_FOUND_NO_VIDEO_REASONS
    # plus the off-mission/already-spoken-for reasons.
    assert MEETING_FOUND_NO_VIDEO_REASONS <= NEVER_RETRY_REASONS
    assert {
        "off-mission",
        "video-without-meeting",
        "unsupported-platform-no-adapter",
        "ingested",
        "queued",
        "already-covered",
    } <= NEVER_RETRY_REASONS
    # the "found nothing at all" set and the "never retry" set don't
    # overlap -- a row can't be both.
    assert NO_MEETING_CONTENT_REASONS & NEVER_RETRY_REASONS == set()


@pytest.mark.parametrize(
    "reason",
    [
        "no-platform-link-found",
        "no-meeting-nor-video",
        "no-meetings-found",
        "no-platform-signature",
    ],
)
def test_is_retry_worthy_no_meeting_trigger_retries_found_nothing_reasons(reason):
    assert is_retry_worthy(reason, trigger="no-meeting") is True


@pytest.mark.parametrize(
    "reason", ["no-platform-link-found", "no-meeting-nor-video", "no-meetings-found"]
)
def test_is_retry_worthy_access_trigger_does_not_retry_known_content_reasons(reason):
    # these three are genuine CONTENT_REASONS members (WO-181's original
    # taxonomy) -- trigger="access" stops at the primary for them.
    # "no-platform-signature" is WO-184-only and NOT in CONTENT_REASONS,
    # so under trigger="access" it falls into the "unrecognized reason"
    # case and IS retry-worthy there too -- tested separately below.
    assert is_retry_worthy(reason, trigger="access") is False


def test_is_retry_worthy_access_trigger_treats_wo184_only_reason_as_unrecognized():
    assert is_retry_worthy("no-platform-signature", trigger="access") is True


@pytest.mark.parametrize(
    "reason",
    [
        "meeting-without-video",
        "no-video-found",
        "off-mission",
        "video-without-meeting",
        "unsupported-platform-no-adapter",
        "ingested",
        "queued",
        "already-covered",
    ],
)
def test_is_retry_worthy_no_meeting_trigger_never_retries_these(reason):
    assert is_retry_worthy(reason, trigger="no-meeting") is False


def test_is_retry_worthy_blank_or_never_tested_reason():
    # Adamsville city, AL shape: never tested at all.
    assert is_retry_worthy("", trigger="no-meeting") is True
    assert is_retry_worthy(None, trigger="no-meeting") is True
    # WO-181's original trigger treats a blank/unrecognized reason as
    # retry-worthy too (unknown is not a confirmed content dead-end).
    assert is_retry_worthy("", trigger="access") is True


@pytest.mark.parametrize("reason", list(ACCESS_REASONS))
def test_is_retry_worthy_access_reasons_retry_under_both_triggers(reason):
    assert is_retry_worthy(reason, trigger="access") is True
    assert is_retry_worthy(reason, trigger="no-meeting") is True


def test_is_retry_worthy_rejects_unknown_trigger():
    with pytest.raises(ValueError):
        is_retry_worthy("dns-unresolvable", trigger="bogus")


@pytest.mark.asyncio
async def test_no_meeting_trigger_retries_alternate_after_no_platform_link_found():
    """Albertville city, AL shape: the primary genuinely found nothing.
    Under trigger="no-meeting" the alternate IS tried (unlike the
    trigger="access" default, which stops at the primary -- see
    test_content_reject_on_primary_never_tries_alternate above)."""
    row = {
        "city_name": "Albertville city",
        "state_or_province": "Alabama",
        "domain": "cityofalbertvilleal.gov",
        "alternate_domains": "cityofalbertville.com",
        "alternate_urls": "",
        "reject_reason": "no-platform-link-found",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "cityofalbertvilleal.gov": LadderOutcome(reason="no-platform-link-found"),
            "cityofalbertville.com": LadderOutcome(
                reason=FOUND,
                platform="civicplus",
                hit_url="https://cityofalbertville.com/AgendaCenter",
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn, trigger="no-meeting")
    assert result.outcome.reason == FOUND
    assert result.answered_domain == "cityofalbertville.com"
    assert ladder_fn.calls == ["cityofalbertvilleal.gov", "cityofalbertville.com"]
    assert decide_promotion(result) is True


@pytest.mark.asyncio
async def test_no_meeting_trigger_never_retries_meeting_without_video():
    """Beverly Hills city, CA shape: a real meeting (via Granicus) was
    already found on the primary, just without video. Ryan's rule is
    explicit that this is "very high quality" on its own -- the main
    retry never fires for it, under either trigger."""
    row = {
        "city_name": "Beverly Hills city",
        "state_or_province": "California",
        "domain": "beverlyhills.gov",
        "alternate_domains": "beverlyhills.org",
        "alternate_urls": "",
        "reject_reason": "meeting-without-video",
        "suspected_meeting_link_provider": "granicus",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "beverlyhills.gov": LadderOutcome(reason="meeting-without-video"),
            "beverlyhills.org": LadderOutcome(
                reason=FOUND, platform="youtube", hit_url="https://youtube.com/x"
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn, trigger="no-meeting")
    assert result.answered_domain == "beverlyhills.gov"
    assert ladder_fn.calls == ["beverlyhills.gov"]  # alternate never touched
    assert decide_promotion(result) is False


@pytest.mark.asyncio
async def test_no_meeting_trigger_retries_a_never_tested_blank_reason():
    """Adamsville city, AL shape: never tested at all (blank
    reject_reason) -- still retry-worthy under trigger="no-meeting"."""
    row = {
        "city_name": "Adamsville city",
        "state_or_province": "Alabama",
        "domain": "cityofadamsville.gov",
        "alternate_domains": "cityofadamsville.org",
        "alternate_urls": "",
        "reject_reason": "",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "cityofadamsville.gov": LadderOutcome(reason="no-platform-link-found"),
            "cityofadamsville.org": LadderOutcome(
                reason=FOUND,
                platform="civicplus",
                hit_url="https://cityofadamsville.org/AgendaCenter",
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn, trigger="no-meeting")
    assert result.outcome.reason == FOUND
    assert result.answered_domain == "cityofadamsville.org"


@pytest.mark.asyncio
async def test_when_primary_itself_found_nothing_is_promoted_and_vice_versa():
    row = {
        "domain": "cityofalbertvilleal.gov",
        "alternate_domains": "cityofalbertville.com",
    }
    # primary answers FOUND -- keep the primary, no promotion.
    ladder_fn_primary_found = _scripted_ladder_fn(
        {
            "cityofalbertvilleal.gov": LadderOutcome(
                reason=FOUND, platform="civicplus", hit_url="x"
            )
        }
    )
    result = await ladder_with_alternates(
        row, ladder_fn_primary_found, trigger="no-meeting"
    )
    assert result.answered_domain == "cityofalbertvilleal.gov"
    assert decide_promotion(result) is False

    # nothing at all answers FOUND -- no promotion either.
    ladder_fn_nothing = _scripted_ladder_fn(
        {
            "cityofalbertvilleal.gov": LadderOutcome(reason="no-platform-link-found"),
            "cityofalbertville.com": LadderOutcome(reason="dns-unresolvable"),
        }
    )
    result2 = await ladder_with_alternates(row, ladder_fn_nothing, trigger="no-meeting")
    assert decide_promotion(result2) is False


@pytest.mark.asyncio
async def test_apply_promotion_moves_old_primary_into_alternate_domains():
    row = {
        "city_name": "Albertville city",
        "state_or_province": "Alabama",
        "domain": "cityofalbertvilleal.gov",
        "alternate_domains": "cityofalbertville.com;another-old-alt.example",
        "alternate_urls": "",
        "reject_reason": "no-platform-link-found",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "cityofalbertvilleal.gov": LadderOutcome(reason="no-platform-link-found"),
            "cityofalbertville.com": LadderOutcome(
                reason=FOUND, platform="civicplus", hit_url="x"
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn, trigger="no-meeting")
    assert decide_promotion(result) is True
    new_row = apply_promotion(row, result)
    assert new_row["domain"] == "cityofalbertville.com"
    # old primary is kept, never dropped; the other pre-existing
    # alternate (never tried, since we stopped at the first FOUND) is
    # kept too.
    assert (
        new_row["alternate_domains"]
        == "another-old-alt.example;cityofalbertvilleal.gov"
    )
    # apply_promotion never mutates the row it was given.
    assert row["domain"] == "cityofalbertvilleal.gov"


@pytest.mark.asyncio
async def test_apply_promotion_is_idempotent_when_promoted_domain_already_listed():
    row = {
        "domain": "cityofalbertvilleal.gov",
        "alternate_domains": "cityofalbertville.com",
    }
    ladder_fn = _scripted_ladder_fn(
        {
            "cityofalbertvilleal.gov": LadderOutcome(reason="no-platform-link-found"),
            "cityofalbertville.com": LadderOutcome(
                reason=FOUND, platform="x", hit_url="x"
            ),
        }
    )
    result = await ladder_with_alternates(row, ladder_fn, trigger="no-meeting")
    new_row = apply_promotion(row, result)
    assert new_row["domain"] == "cityofalbertville.com"
    assert new_row["alternate_domains"] == "cityofalbertvilleal.gov"


def _scripted_fetch(pages):
    """pages: {url: (html_or_None, final_url, error_kind)} -- returns an
    async fetch_one_fn plus the call log, same shape as the real
    fetch_one() FetchResult (duck-typed: .html/.final_url/.error_kind/
    .error)."""

    class _R:
        def __init__(self, html, final_url, error_kind="", error=""):
            self.html = html
            self.final_url = final_url
            self.error_kind = error_kind
            self.error = error

    calls = []

    async def fetch_one_fn(url, headers):
        calls.append(url)
        html, final_url, error_kind = pages.get(url, (None, url, "connection"))
        return _R(html, final_url, error_kind)

    fetch_one_fn.calls = calls
    return fetch_one_fn


def _never_challenge(html):
    return False


@pytest.mark.asyncio
async def test_one_hop_alternate_finds_platform_link_on_home_page():
    row = {"suspected_meeting_link_provider": "granicus"}  # Beverly Hills CA shape
    fetch = _scripted_fetch(
        {
            "https://beverlyhills.org": (
                "<html>home</html>",
                "https://beverlyhills.org",
                "",
            )
        }
    )

    def find_platform_link_fn(html, final_url):
        return ("youtube", "https://youtube.com/watch?v=x")

    def find_hop_links_fn(html, final_url):
        return []

    result = await one_hop_alternate(
        row,
        "beverlyhills.org",
        fetch,
        {"User-Agent": "test"},
        _never_challenge,
        find_platform_link_fn,
        find_hop_links_fn,
    )
    assert result.reason == FOUND
    assert result.platform == "youtube"
    # granicus (primary's known platform) != youtube -- a genuinely
    # different platform, per Ryan's "may surface video" instruction.
    assert result.differs_from_primary is True
    assert result.hop_url is None


@pytest.mark.asyncio
async def test_one_hop_alternate_same_platform_as_primary_is_not_a_new_view():
    row = {"suspected_meeting_link_provider": "granicus"}

    def find_platform_link_fn(html, final_url):
        return ("granicus", "https://granicus.example/x")

    fetch = _scripted_fetch(
        {
            "https://beverlyhills.org": (
                "<html>home</html>",
                "https://beverlyhills.org",
                "",
            )
        }
    )
    result = await one_hop_alternate(
        row,
        "beverlyhills.org",
        fetch,
        {"User-Agent": "test"},
        _never_challenge,
        find_platform_link_fn,
        lambda html, url: [],
    )
    assert result.reason == FOUND
    assert result.differs_from_primary is False


@pytest.mark.asyncio
async def test_one_hop_alternate_follows_one_hop_link_when_home_page_has_none():
    row = {}
    fetch = _scripted_fetch(
        {
            "https://cityofalbertville.com": (
                "<html><a href='https://cityofalbertville.com/meetings'>Meetings</a></html>",
                "https://cityofalbertville.com",
                "",
            ),
            "https://cityofalbertville.com/meetings": (
                "<html>meetings page</html>",
                "https://cityofalbertville.com/meetings",
                "",
            ),
        }
    )
    calls_to_find_platform = []

    def find_platform_link_fn(html, final_url):
        calls_to_find_platform.append(final_url)
        if "meetings" in final_url:
            return ("civicplus", "https://cityofalbertville.com/AgendaCenter")
        return None

    def find_hop_links_fn(html, final_url):
        return ["https://cityofalbertville.com/meetings"]

    result = await one_hop_alternate(
        row,
        "cityofalbertville.com",
        fetch,
        {"User-Agent": "test"},
        _never_challenge,
        find_platform_link_fn,
        find_hop_links_fn,
    )
    assert result.reason == FOUND
    assert result.hop_url == "https://cityofalbertville.com/meetings"
    assert result.differs_from_primary is True  # no known platform at all yet


@pytest.mark.asyncio
async def test_one_hop_alternate_no_platform_link_anywhere():
    row = {}
    fetch = _scripted_fetch(
        {
            "https://cedarbluff-al.org": (
                "<html>nothing here</html>",
                "https://cedarbluff-al.org",
                "",
            )
        }
    )
    result = await one_hop_alternate(
        row,
        "cedarbluff-al.org",
        fetch,
        {"User-Agent": "test"},
        _never_challenge,
        lambda html, url: None,
        lambda html, url: [],
    )
    assert result.reason == "no-platform-link-found"
    assert result.differs_from_primary is None


@pytest.mark.asyncio
async def test_one_hop_alternate_dns_unresolvable():
    row = {}

    async def fetch_one_fn(url, headers):
        class _R:
            html = None
            final_url = url
            error_kind = "dns"
            error = "getaddrinfo failed"

        return _R()

    result = await one_hop_alternate(
        row,
        "cedarbluff-al.org",
        fetch_one_fn,
        {},
        _never_challenge,
        lambda h, u: None,
        lambda h, u: [],
    )
    assert result.reason == "dns-unresolvable"


# --- WO-193 (2026-09-11): classify_domain_shape / canonicalize_domain ---
#
# Every value below is a REAL `domain`/`alternate_domains` cell from
# `~/Documents/rtr-business/research/jurisdiction_coverage.csv` as of
# 2026-09-11, confirmed by directly reading the file while writing this
# WO (not an invented example):
#
# - Fairfax County, VA (`us:county:51059`): `domain`
#   `https://www.fairfaxcounty.gov/` -- the exact example BACKLOG.md's
#   WO-174 entry named as a "full URL". Its trailing `/` is the site
#   root, not a real page, so it classifies as `scheme_host` (no extra
#   URL to preserve) rather than `scheme_host_path` -- a real path is
#   something beyond that root, like Campbellton NB's (below).
# - Campbellton, NB (`ca:csd:1314014`): `domain`
#   `https://capacadie.ca/fr/` -- a real path beyond the root
#   (`scheme_host_path`), preserved into `alternate_urls`.
# - Seminole County, FL (`us:county:12117`): `domain`
#   `www.seminolecountyfl.gov:443` -- an explicit port.
# - Warren County, MS (`us:county:28149`): `domain` `www.Co.Warren.Ms.Us`
#   -- uppercase.
# - Magnolia boro, NJ (`us:place:3442630`): `domain` `magnolia-nj.org.`
#   -- a trailing dot.
# - a Quebec CSD (`ca:csd:2439135`): `domain`
#   `http://www.msvalere.qc,ca` -- a comma where a dot belongs; NOT two
#   hosts (splitting on the comma gives "www.msvalere.qc" and "ca", and
#   "ca" alone is not a real second hostname), so this stays one odd
#   host rather than being torn in two.
# - a Quebec CSD (`ca:csd:3554029`, Casey): `domain` `http://Casey.ca` --
#   scheme + uppercase host together.
# - a NY special district (`us:sd:5103640`): `domain`
#   `regionalwebtv.com/spotsysb` -- a real path with NO scheme, the
#   file's only row shaped this way.
# - a Facebook profile URL with an HTML-entity-encoded `&` in its query
#   (`https://www.facebook.com/profile.php?id=61558365536288&amp;
#   mibextid=LQQJ4d`) -- the comma this decodes to lives in the QUERY,
#   not the host, so this is an ordinary `scheme_host_query` shape, not
#   `other`; this is the case that makes classification look only at the
#   parsed host component instead of the whole raw string.


def test_classify_domain_shape_bare_host_and_www():
    assert classify_domain_shape("cityofabbeville.org") == "bare_host"
    assert classify_domain_shape("www.athensal.us") == "bare_host_www"
    assert classify_domain_shape("") == "blank"
    assert classify_domain_shape(None) == "blank"


def test_classify_domain_shape_scheme_variants():
    assert classify_domain_shape("https://choctawcountyal.org") == "scheme_host"
    # a trailing "/" alone is the site root, not a real page.
    assert classify_domain_shape("https://www.fairfaxcounty.gov/") == "scheme_host"
    assert classify_domain_shape("https://capacadie.ca/fr/") == "scheme_host_path"
    assert (
        classify_domain_shape(
            "https://www.facebook.com/profile.php?id=61558365536288&amp;mibextid=LQQJ4d"
        )
        == "scheme_host_query"
    )


def test_classify_domain_shape_other_for_port_case_dot_and_no_scheme_path():
    assert classify_domain_shape("www.seminolecountyfl.gov:443") == "other"
    assert classify_domain_shape("www.Co.Warren.Ms.Us") == "other"
    assert classify_domain_shape("magnolia-nj.org.") == "other"
    assert classify_domain_shape("http://Casey.ca") == "other"
    assert classify_domain_shape("regionalwebtv.com/spotsysb") == "other"
    assert classify_domain_shape("http://www.msvalere.qc,ca") == "other"


def test_canonicalize_domain_bare_host_is_unchanged():
    assert canonicalize_domain("cityofabbeville.org") == ("cityofabbeville.org", None)
    # a leading www. is preserved exactly, never added or stripped.
    assert canonicalize_domain("www.athensal.us") == ("www.athensal.us", None)


def test_canonicalize_domain_strips_scheme_and_preserves_path_as_extra_url():
    host, extra = canonicalize_domain("https://capacadie.ca/fr/")
    assert host == "capacadie.ca"
    assert extra == "https://capacadie.ca/fr/"


def test_canonicalize_domain_scheme_host_only_has_no_extra_url():
    host, extra = canonicalize_domain("https://choctawcountyal.org")
    assert host == "choctawcountyal.org"
    assert extra is None
    # a bare trailing "/" is the site root, not a real page -- nothing
    # to preserve, same as no path at all.
    host, extra = canonicalize_domain("https://www.fairfaxcounty.gov/")
    assert host == "www.fairfaxcounty.gov"
    assert extra is None


def test_canonicalize_domain_strips_port_case_and_trailing_dot():
    assert canonicalize_domain("www.seminolecountyfl.gov:443") == (
        "www.seminolecountyfl.gov",
        None,
    )
    assert canonicalize_domain("www.Co.Warren.Ms.Us") == ("www.co.warren.ms.us", None)
    assert canonicalize_domain("magnolia-nj.org.") == ("magnolia-nj.org", None)
    assert canonicalize_domain("http://Casey.ca") == ("casey.ca", None)


def test_canonicalize_domain_no_scheme_path_gets_a_scheme_for_the_extra_url():
    host, extra = canonicalize_domain("regionalwebtv.com/spotsysb")
    assert host == "regionalwebtv.com"
    assert extra == "https://regionalwebtv.com/spotsysb"


def test_canonicalize_domain_comma_typo_stays_one_host_not_split():
    # "ca" alone is not a real second hostname -- this is one malformed
    # host (a comma where a dot belongs), not two hosts to split apart.
    host, extra = canonicalize_domain("http://www.msvalere.qc,ca")
    assert host == "www.msvalere.qc,ca"
    assert extra is None


def test_canonicalize_domain_never_blanks_a_nonblank_value():
    assert canonicalize_domain("")[0] == ""
    assert canonicalize_domain(None)[0] == ""
    for v in [
        "cityofabbeville.org",
        "https://www.fairfaxcounty.gov/",
        "www.seminolecountyfl.gov:443",
        "http://www.msvalere.qc,ca",
        "False",
    ]:
        host, _ = canonicalize_domain(v)
        assert host != ""
