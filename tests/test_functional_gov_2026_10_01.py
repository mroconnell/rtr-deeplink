"""Functional Gov (CourseVector / WebsiteForGov) site-builder tag and
Meeting Finder hop ranking. Ryan 2026-10-01.

Fixtures are real pages fetched once 2026-10-01 (tests/fixtures/functionalgov/
README.md).
"""

from __future__ import annotations

from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.hop import rank_hops
from scripts.cms_fingerprint import classify
from tests.conftest import load_fixture

BROOKHAVEN_URL = "https://brookhavenboro.com/"
JONESTOWN_URL = "https://jonestownpa.org/"
LOUISA_URL = "https://louisava.gov/government/"
BROOKHAVEN = load_fixture("functionalgov", "home_brookhavenboro_com.html")
JONESTOWN = load_fixture("functionalgov", "home_jonestownpa_org.html")
LOUISA = load_fixture("functionalgov", "government_louisava_gov.html")


def _page(html: str, url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=0,
    )


# ---- fingerprint -------------------------------------------------------


def test_three_real_sites_are_confirmed_functional_gov():
    for html, url in (
        (BROOKHAVEN, BROOKHAVEN_URL),
        (JONESTOWN, JONESTOWN_URL),
        (LOUISA, LOUISA_URL),
    ):
        result = classify(html, url=url)
        assert result.family == "functionalgov"
        assert result.confidence == "confirmed"


def test_script_id_alone_is_confirmed():
    html = "<script id='functional-gov-wp-datatables-script2-js' src='/x.js'></script>"
    result = classify(html)
    assert (result.family, result.confidence) == ("functionalgov", "confirmed")


def test_document_type_alone_never_tags():
    html = '<a href="/document_type/council-minutes/">Minutes</a> borough council'
    assert classify(html).family == "unknown"


def test_document_type_plus_pdf_sentence_plus_government_is_very_likely():
    html = (
        '<a href="/document_type/council-minutes/">Minutes</a>'
        "<p>Click the title to view the PDF.</p> Smithville Borough Council"
    )
    result = classify(html)
    assert (result.family, result.confidence) == ("functionalgov", "very likely")


def test_document_type_plus_pdf_sentence_without_government_does_not_tag():
    html = '<a href="/document_type/forms/">Forms</a><p>Click the title to view the PDF.</p>'
    assert classify(html).family == "unknown"


def test_document_urls_plus_branding_is_likely():
    html = (
        '<a href="/document/budget-2026/">Budget</a>'
        '<a href="/document_type/newsletter/">News</a>'
        "<footer>Design &amp; hosting by CourseVector</footer>"
    )
    result = classify(html)
    assert (result.family, result.confidence) == ("functionalgov", "likely")


def test_branding_alone_is_a_coursevector_customer():
    result = classify("<footer>Design &amp; hosting by CourseVector</footer>")
    assert (result.family, result.confidence) == (
        "coursevector",
        "coursevector customer",
    )


def test_plain_wordpress_is_not_functional_gov():
    assert (
        classify('<link href="/wp-content/themes/x/style.css">').family == "wordpress"
    )


# ---- hop ranking -------------------------------------------------------


def _urls(html: str, url: str) -> list[str]:
    return [h.url for h in rank_hops(_page(html, url), limit=8)]


def test_brookhaven_recordings_link_is_in_top_three():
    top3 = _urls(BROOKHAVEN, BROOKHAVEN_URL)[:3]
    assert any("recordings-council-meetings" in u for u in top3), top3


def test_louisa_meeting_videos_link_is_in_top_three():
    hops = rank_hops(_page(LOUISA, LOUISA_URL), limit=8)
    top3 = [h.anchor for h in hops[:3]]
    assert "Meeting Videos" in top3, [(h.anchor, h.url) for h in hops]


def test_jonestown_agenda_hub_ranks_when_no_recordings_link():
    top3 = _urls(JONESTOWN, JONESTOWN_URL)[:3]
    assert any("council-meeting-minutes-agenda" in u for u in top3), top3


def test_recordings_outrank_pdf_taxonomy_hub_on_functional_gov_page():
    html = (
        "<script id='functional-gov-wp-datatables-script-js' src='/a.js'></script>"
        "<nav><a href='/document_type/council-minutes/'>Council Minutes</a>"
        "<a href='/document_type/council-meeting-recordings/'>Council Meeting "
        "Recordings</a></nav>"
    )
    urls = _urls(html, "https://exampleboro.org/")
    assert urls[0].endswith("/document_type/council-meeting-recordings/")
    assert any(u.endswith("/document_type/council-minutes/") for u in urls)


def test_recordings_path_gets_no_special_rank_on_other_sites():
    html = (
        "<nav><a href='/recordings/'>Stuff</a>"
        "<a href='/document_type/council-minutes/'>Stuff two</a></nav>"
    )
    from app.platforms.meeting_finder import hop

    assert hop._is_functional_gov_page(html, "https://example.gov/") is False
