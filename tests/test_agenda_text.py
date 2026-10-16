"""WO-1966: agenda and packet text, read once at ingest and stored as
deduplicated AgendaVersion rows.

What is real here and what is not, so a later reader can tell them apart:

* REAL: the CivicPlus agenda/packet links come from the raw-saved
  nc-durham.civicplus.com page (tests/fixtures/civicplus/
  durham_agendacenter_citycouncil.html). The CivicClerk links come from the
  real Emporia KS event fixture. The PDF bytes are a real PDF served by a
  CivicPlus site (ga-richmondhill2.civicplus.com DocumentCenter, saved
  2026-09-12) -- a city charter, NOT an agenda. No real agenda PDF could be
  saved for this PR: the cloud session's network proxy refused every
  government host (civicplus.com, civicclerk.com, the Wayback Machine).
* SYNTHETIC: the agenda TEXT used for the CivicClerk plain-text route and
  the guard tests is hand-written. Its shape follows the real Los Altos
  Hills masthead recorded in BACKLOG_DONE.md ("Town of Los Altos Hills /
  City Council Regular Meeting Agenda / Thursday, June 18, 2026 ..."), and
  the wrong-year case follows rtr-upcoming's real Milpitas example
  (a 2019 minutes file under a 2026 meeting). Each such test says so.
"""

import sys

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

import archive.main
from app import agenda_text
from app.platforms.civicplus import CivicPlusAssetFinder
from app.utils import robots_check, url_guard
from archive.db import agenda_versions, crud
from archive.utils import agenda_ingest

# Imported before conftest's autouse fixture replaces it with a no-op.
from archive.utils.agenda_ingest import read_and_store as real_read_and_store
from tests.aiohttp_mock import FakeResponse, mock_session
from tests.conftest import load_fixture, load_fixture_bytes

client = TestClient(archive.main.app)

DURHAM_PAGE = "https://nc-durham.civicplus.com/AgendaCenter/City-Council-4"
# Real publishedFiles URLs from tests/fixtures/civicclerk/emporiaks_event585.json.
EMPORIA_AGENDA = (
    "https://emporiaks.api.civicclerk.com/v1/Meetings/"
    "GetMeetingFile(fileId=1620,plainText=false)"
)
EMPORIA_PACKET = (
    "https://emporiaks.api.civicclerk.com/v1/Meetings/"
    "GetMeetingFile(fileId=1621,plainText=false)"
)
RICHMOND_HILL_PDF = load_fixture_bytes(
    "civicplus", "richmondhill_documentcenter_5032.bin"
)

# Synthetic agenda text (see module docstring), long enough and procedural
# enough to pass looks_like_shell().
SYNTHETIC_AGENDA = (
    "City of Emporia / City Commission Regular Meeting Agenda / "
    "Wednesday, June 18, 2026, at 6:00 PM\n"
    "1. Call to Order\n2. Roll Call\n3. Public Comment\n"
    "4. Consent Agenda: approval of the minutes of June 4, 2026\n"
    "5. Ordinance 26-14 amending the zoning code\n6. Adjourn\n"
) * 2


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """No real DNS and no real robots.txt fetch."""
    monkeypatch.setattr(url_guard, "_resolve_hostname", lambda h: ["93.184.216.34"])

    async def _allowed(url):
        return True, None

    monkeypatch.setattr(robots_check, "check_url", _allowed)


def _durham_links():
    """The agenda and packet links of the first real Durham row that has
    both, read with the adapter's own parser."""
    soup = BeautifulSoup(
        load_fixture("civicplus", "durham_agendacenter_citycouncil.html"), "html.parser"
    )
    for row in soup.select("tr.catAgendaRow"):
        agenda, packet = CivicPlusAssetFinder._extract_agenda_and_packet_links(
            row, DURHAM_PAGE
        )
        if agenda and packet:
            return agenda, packet
    raise AssertionError("no Durham row with both links")


# --- which addresses get read ----------------------------------------------


def test_civicplus_real_links_try_pdf_first_then_html_and_packet():
    agenda, packet = _durham_links()
    assert agenda.endswith("?html=true")
    cands = agenda_text.candidates_for(agenda, packet)
    assert [(c.doc_role, c.url) for c in cands] == [
        ("agenda", agenda.split("?")[0]),
        ("agenda", agenda),
        ("packet", packet),
    ]


def test_civicclerk_real_links_try_plain_text_then_file_stream():
    cands = agenda_text.candidates_for(EMPORIA_AGENDA, EMPORIA_PACKET)
    assert [(c.doc_role, c.mode, c.url) for c in cands] == [
        (
            "agenda",
            "civicclerk_plaintext",
            EMPORIA_AGENDA.replace("plainText=false", "plainText=true"),
        ),
        (
            "agenda",
            "file",
            EMPORIA_AGENDA.replace("GetMeetingFile(", "GetMeetingFileStream("),
        ),
        (
            "packet",
            "civicclerk_plaintext",
            EMPORIA_PACKET.replace("plainText=false", "plainText=true"),
        ),
        (
            "packet",
            "file",
            EMPORIA_PACKET.replace("GetMeetingFile(", "GetMeetingFileStream("),
        ),
    ]


@pytest.mark.parametrize(
    "link",
    [
        # Shapes this PR deliberately does not read yet.
        "https://boston.legistar.com/View.ashx?M=A&ID=1&GUID=X",
        "https://meetings.municode.com/adaHtmlDocument/index?cc=X&me=Y",
        "https://example.civicclerk.com/agenda.pdf",
        None,
    ],
)
def test_other_platforms_are_not_read(link):
    assert agenda_text.candidates_for(link, None) == []
    assert not agenda_ingest.wanted(link, None)


# --- extraction ----------------------------------------------------------------


def test_real_civicplus_pdf_extracts_in_process():
    text, fmt = agenda_text.extract(RICHMOND_HILL_PDF, "application/pdf")
    assert fmt == "pdf"
    assert "City of Richmond Hill" in text
    assert len(text) > 50_000
    assert agenda_text.mangled_count(text) == 0


def test_bytes_beat_a_lying_content_type():
    # The real PDF, labelled as HTML: still read as a PDF.
    text, fmt = agenda_text.extract(RICHMOND_HILL_PDF, "text/html")
    assert fmt == "pdf" and "Richmond Hill" in text


async def test_child_process_gives_the_same_text_as_in_process(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(RICHMOND_HILL_PDF)
    child_text, child_fmt = await agenda_text.extract_pdf_isolated(str(path))
    text, fmt = agenda_text.extract(RICHMOND_HILL_PDF, "application/pdf")
    # Same bytes out, so the same content hash: re-reading through the child
    # can never look like an amendment.
    assert (child_text, child_fmt) == (text, fmt)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="RLIMIT_DATA is Linux-only"
)
async def test_memory_ceiling_reports_too_heavy(tmp_path, monkeypatch):
    path = tmp_path / "doc.pdf"
    path.write_bytes(RICHMOND_HILL_PDF)
    monkeypatch.setattr(agenda_text, "EXTRACT_MEMORY_MB", 20)
    with pytest.raises(agenda_text.TooHeavy):
        await agenda_text.extract_pdf_isolated(str(path))


def test_html_drops_scripts_and_word_comments():
    # Synthetic: the narrow branch rtr-upcoming found on Millbrae's real
    # Word-exported HTML ("supportLists" 58 times).
    html = (
        b"<html><head><script>var x=1;</script></head><body>"
        b"<!--[if !supportLists]-->1.<!--[endif]--><p>Call to Order</p></body></html>"
    )
    text, fmt = agenda_text.extract(html, "text/html; charset=utf-8")
    assert fmt == "html"
    assert "supportLists" not in text and "var x" not in text
    assert "Call to Order" in text


def test_mangled_words_are_counted_and_camel_case_is_not():
    # Synthetic words, taken from rtr-upcoming's real damage cases.
    assert agenda_text.mangled_count("parBcipate submiLed reportedRequest") == 3
    assert agenda_text.mangled_count("eScribe McDonald iPhone") == 0


# --- guards -------------------------------------------------------------------


def test_login_page_is_not_an_agenda():
    # Synthetic, the shape of PrimeGov's real 116-character sign-in page.
    assert agenda_text.looks_like_shell("Sign In  Password  Forgot password?")


def test_wrong_year_document_is_rejected():
    # Synthetic text in the shape of rtr-upcoming's real Milpitas case.
    text = "CITY OF MILPITAS MEETING MINUTES September 25, 2019 Planning Commission"
    assert agenda_text.wrong_document(text, "2026-09-09")


def test_nearby_or_undated_documents_pass():
    assert agenda_text.wrong_document(SYNTHETIC_AGENDA, "2026-06-18") is None
    assert agenda_text.wrong_document("Agenda. Call to order.", "2026-06-18") is None
    # A packet citing last month's minutes is ordinary.
    assert agenda_text.wrong_document("Minutes of May 20, 2026", "2026-06-18") is None


def test_numeric_date_is_read_both_ways():
    # Synthetic. 12/01/2026 is 1 December in the US and 12 January in
    # Canada; for a 2026-01-12 meeting the Canadian reading must count.
    assert agenda_text.wrong_document("Agenda 12/01/2026", "2026-01-12") is None


# --- reading over the network (mocked) ---------------------------------------


async def test_civicclerk_plain_text_route():
    plain = EMPORIA_AGENDA.replace("plainText=false", "plainText=true")
    blob = "https://blob.example.net/agenda.txt?sv=2020&sig=SECRET"
    routes = {
        plain: FakeResponse(text='{"blobUri": "%s"}' % blob),
        blob: FakeResponse(text=SYNTHETIC_AGENDA),
    }
    with mock_session(routes):
        results = await agenda_text.read_documents(EMPORIA_AGENDA, None, "2026-06-18")
    assert len(results) == 1
    r = results[0]
    assert r.doc_role == "agenda" and r.text and r.format == "text (civicclerk)"
    assert r.content_hash == agenda_text.content_hash(r.text)
    # The signed query string is never kept.
    assert r.resolved_url == "https://blob.example.net/agenda.txt"


async def test_civicclerk_zero_bytes_means_not_published():
    plain = EMPORIA_AGENDA.replace("plainText=false", "plainText=true")
    stream = EMPORIA_AGENDA.replace("GetMeetingFile(", "GetMeetingFileStream(")
    routes = {
        plain: FakeResponse(text=""),
        stream: FakeResponse(raw=b"", headers={"Content-Type": "application/pdf"}),
    }
    with mock_session(routes):
        (r,) = await agenda_text.read_documents(EMPORIA_AGENDA, None, "2026-06-18")
    assert r.text is None and r.not_published


async def test_civicclerk_wrong_year_document_is_not_stored():
    plain = EMPORIA_AGENDA.replace("plainText=false", "plainText=true")
    stream = EMPORIA_AGENDA.replace("GetMeetingFile(", "GetMeetingFileStream(")
    blob = "https://blob.example.net/old.txt"
    old = "MEETING MINUTES September 25, 2019. Call to order. Roll call. " * 10
    routes = {
        plain: FakeResponse(text='{"blobUri": "%s"}' % blob),
        blob: FakeResponse(text=old),
        stream: FakeResponse(raw=old.encode(), headers={"Content-Type": "text/plain"}),
    }
    with mock_session(routes):
        (r,) = await agenda_text.read_documents(EMPORIA_AGENDA, None, "2026-09-09")
    assert r.text is None and "not this meeting's document" in r.error


async def test_civicplus_real_pdf_through_the_child_process():
    agenda, packet = _durham_links()
    pdf_url = agenda.split("?")[0]
    routes = {
        pdf_url: FakeResponse(
            raw=RICHMOND_HILL_PDF, headers={"Content-Type": "application/pdf"}
        ),
        packet: FakeResponse(
            raw=RICHMOND_HILL_PDF, headers={"Content-Type": "application/pdf"}
        ),
    }
    with mock_session(routes):
        results = await agenda_text.read_documents(agenda, packet, None)
    by_role = {r.doc_role: r for r in results}
    assert set(by_role) == {"agenda", "packet"}
    assert by_role["agenda"].format == "pdf"
    assert "Richmond Hill" in by_role["agenda"].text
    assert by_role["agenda"].source_url == pdf_url


async def test_oversized_document_is_refused_not_truncated(monkeypatch):
    agenda, _packet = _durham_links()
    pdf_url = agenda.split("?")[0]
    monkeypatch.setattr(agenda_text, "MAX_BYTES", 1000)
    routes = {
        pdf_url: FakeResponse(raw=RICHMOND_HILL_PDF),
        # The HTML rendition is the fallback; it answers with a shell page.
        agenda: FakeResponse(text="<html><body>Agenda - 08/20/2026</body></html>"),
    }
    with mock_session(routes):
        (r,) = await agenda_text.read_documents(agenda, None, None)
    assert r.text is None


async def test_robots_disallow_means_no_request(monkeypatch):
    async def _disallowed(url):
        return False, None

    monkeypatch.setattr(robots_check, "check_url", _disallowed)
    with mock_session({}):  # any request would fail as unmocked
        (r,) = await agenda_text.read_documents(EMPORIA_AGENDA, None, None)
    assert r.error == "robots.txt disallows this address"


async def test_read_documents_never_raises():
    # No routes at all: every request raises inside the mock.
    with mock_session({}):
        results = await agenda_text.read_documents(EMPORIA_AGENDA, EMPORIA_PACKET, None)
    assert {r.doc_role for r in results} == {"agenda", "packet"}
    assert all(r.error and not r.text for r in results)


# --- storing at ingest ---------------------------------------------------------


async def _page(external_id: str) -> int:
    payload = {
        "platform": "civicclerk",
        "source_url": f"https://example.com/wo1966/{external_id}",
        "external_id": external_id,
        "title": f"WO-1966 {external_id}",
        "date": "2026-06-18",
        "jurisdiction": "Wotest City, KS",
        "video_url": None,
        "video_format": None,
        "segments": [],
        "agenda_items": [],
        "agenda_link": EMPORIA_AGENDA,
        "transcript_language": None,
        "transcript_warnings": [],
    }
    return (await crud.ingest_resolution(payload, payload["source_url"]))["page_id"]


def _fake_reads(monkeypatch, texts: dict):
    calls = []

    async def _read(
        agenda_link, packet_link, meeting_date, *, skip_roles=frozenset(), session=None
    ):
        calls.append(set(skip_roles))
        return [
            agenda_text.ReadResult(
                doc_role=role,
                source_url=f"https://example.com/{role}",
                text=t,
                format="pdf",
                content_hash=agenda_text.content_hash(t),
            )
            for role, t in texts.items()
            if role not in skip_roles
        ]

    monkeypatch.setattr(agenda_text, "read_documents", _read)
    return calls


async def test_same_text_is_stored_once_and_a_change_is_a_new_version(monkeypatch):
    page_id = await _page("dedupe")
    _fake_reads(
        monkeypatch, {"agenda": SYNTHETIC_AGENDA, "packet": SYNTHETIC_AGENDA * 3}
    )

    first = await real_read_and_store(
        page_id, EMPORIA_AGENDA, EMPORIA_PACKET, "2026-06-18"
    )
    assert sorted(s["outcome"] for s in first) == ["created", "created"]

    # A re-ingest within the recheck window reads nothing.
    second = await real_read_and_store(
        page_id, EMPORIA_AGENDA, EMPORIA_PACKET, "2026-06-18"
    )
    assert sorted(s["outcome"] for s in second) == [
        "recently_checked",
        "recently_checked",
    ]

    # Past the window, the same text stores nothing new...
    monkeypatch.setattr(agenda_ingest, "AGENDA_RECHECK_HOURS", 0)
    third = await real_read_and_store(
        page_id, EMPORIA_AGENDA, EMPORIA_PACKET, "2026-06-18"
    )
    assert sorted(s["outcome"] for s in third) == ["unchanged", "unchanged"]

    # ...and an amended agenda is a new row; the packet is untouched.
    _fake_reads(
        monkeypatch,
        {"agenda": SYNTHETIC_AGENDA + "7. Added item", "packet": SYNTHETIC_AGENDA * 3},
    )
    fourth = await real_read_and_store(
        page_id, EMPORIA_AGENDA, EMPORIA_PACKET, "2026-06-18"
    )
    assert {s["doc_role"]: s["outcome"] for s in fourth} == {
        "agenda": "created",
        "packet": "unchanged",
    }

    versions = await agenda_versions.list_versions(page_id)
    assert sorted(v["doc_role"] for v in versions) == ["agenda", "agenda", "packet"]
    assert all(v["extractor"] == agenda_text.EXTRACTOR_NAME for v in versions)
    assert "text" not in versions[0]


async def test_read_and_store_never_raises(monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("database down")

    monkeypatch.setattr(agenda_versions, "roles_checked_since", _boom)
    out = await real_read_and_store(1, EMPORIA_AGENDA, None, None)
    assert out == [{"outcome": "error"}]


def _ingest_body(external_id: str, agenda_link: str) -> dict:
    return {
        "platform": "civicclerk",
        "source_url": f"https://example.com/wo1966/{external_id}",
        "external_id": external_id,
        "title": f"WO-1966 {external_id}",
        "date": "2026-06-18",
        "jurisdiction": "Wotest City, KS",
        "agenda_link": agenda_link,
        "packet_link": EMPORIA_PACKET,
        "input_url_normalized": f"https://example.com/wo1966/{external_id}",
    }


def test_ingest_queues_the_read_for_a_wired_link(monkeypatch):
    calls = []

    async def _record(*args):
        calls.append(args)
        return []

    monkeypatch.setattr(agenda_ingest, "read_and_store", _record)
    response = client.post(
        "/internal/ingest",
        json=_ingest_body("endpoint-civicclerk", EMPORIA_AGENDA),
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    page_id = response.json()["page_id"]
    assert calls == [(page_id, EMPORIA_AGENDA, EMPORIA_PACKET, "2026-06-18")]


def test_ingest_skips_the_read_for_other_platforms(monkeypatch):
    calls = []

    async def _record(*args):
        calls.append(args)
        return []

    monkeypatch.setattr(agenda_ingest, "read_and_store", _record)
    body = _ingest_body(
        "endpoint-legistar", "https://boston.legistar.com/View.ashx?M=A&ID=9"
    )
    body["packet_link"] = None
    response = client.post(
        "/internal/ingest", json=body, headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    assert calls == []
