"""Tests for WO-222: the sweep ingest helpers (`scripts/wo134_confirmed_
hits_ingest.py`'s `process_row()`, `scripts/bulk_ingest.py`'s
`process_one()`/`main()`) now send the row's own `gov_id` in the
`/internal/ingest` payload when they know it, instead of relying on a
`tenant_overrides.csv` pin reaching production before the page is
created (`archive/main.py`'s `IngestRequest.gov_id` /
`archive/db/crud.py`'s `caller_gov_id` already accepted this over HTTP --
see `docs/COVERAGE_HANDOVER.md` §3).

Two levels, per CLAUDE.md's fixture-vs-real-data convention:

1. Payload-level (fixture-free, HTTP mocked out by monkeypatching the
   `_ingest`/`_ingest_with_retry` call each script already makes --
   these tests are about what dict gets BUILT and PASSED, not about
   HTTP plumbing tests/test_bulk_ingest.py already covers): does the
   payload carry `gov_id` when the row has one, and omit the key
   entirely (never send `""`) when it doesn't.
2. crud-level, real SQLite (`archive/db/crud.ingest_resolution()`
   directly, same isolated-DB pattern as tests/test_gov_id_zip_
   recovery.py): does a payload `gov_id` actually key a brand-new page
   on a MULTI_GOV_HOSTS host with no tenant_overrides.csv pin -- and
   does WO-215's manual_override guard still hold when the caller now
   supplies a `gov_id` on a re-ingest (never silently downgrades an
   already-`manual_override`d page's tier, and never overwrites a
   DIFFERENT existing real gov_id -- raises GovernmentMismatch instead,
   same as any other caller_gov_id push).

Real gov_ids only (CLAUDE.md's synthetic-test convention): `us:place:
0600562` (Alameda, CA) and `us:place:5502375` (Appleton, WI) are both
already confirmed real, unambiguous Census place ids by tests/
test_gov_id_zip_recovery.py -- reused here rather than inventing new
ones.
"""

import pytest

import scripts.wo134_confirmed_hits_ingest as wo134
from app.platforms import register_all_finders
from app.platforms.models import ResolvedMeeting, TranscriptSegment
from archive.db import crud

register_all_finders()

ALAMEDA_CA = "us:place:0600562"
APPLETON_WI = "us:place:5502375"


@pytest.fixture(autouse=True)
def _rules_file(tmp_path, monkeypatch):
    """Same isolation as tests/test_jurisdiction_override.py's own fixture
    of the same name: override_jurisdiction() appends a tenant_overrides-
    shaped pending-rules line as a side effect, and its default path
    lives under /tmp -- redirected into this test's own tmp dir so a
    parallel test run (or a real operator's /tmp file) is never touched
    or accumulated into."""
    monkeypatch.setattr(
        crud, "JURISDICTION_OVERRIDE_RULES_FILE", tmp_path / "pending.csv"
    )


# --------------------------------------------------------------------------
# 1a. scripts/wo134_confirmed_hits_ingest.py's process_row()
# --------------------------------------------------------------------------


def _wo134_row(gov_id, source_url):
    return {
        "gov_id": gov_id,
        "unit_name": "Test City, ST",
        "homepage": "",
        "hop2_urls": "",
        "hit_source_urls": f"granicus={source_url}",
    }


def _fake_locate_platform_url(source_url):
    async def _fake(session, platform, hit_url, hop2_urls, homepage):
        return source_url, ""

    return _fake


def _fake_resolve_seed(result, final_seed):
    async def _fake(session, platform, seed_url):
        return result, final_seed, False

    return _fake


def _segments_result(source_url):
    return ResolvedMeeting(
        platform="granicus",
        source_url=source_url,
        title="Test City Council Meeting",
        date="2026-01-01",
        jurisdiction="Test City, ST",
        segments=[TranscriptSegment(start=0.0, end=1.0, text="hello")],
    )


async def test_process_row_sends_gov_id_when_row_has_one(monkeypatch):
    source_url = "https://wo222-a.granicus.com/MediaPlayer.php?view_id=1&clip_id=1"
    row = _wo134_row("test:wo222:0001", source_url)
    result = _segments_result(source_url)

    monkeypatch.setattr(
        wo134, "locate_platform_url", _fake_locate_platform_url(source_url)
    )
    monkeypatch.setattr(wo134, "resolve_seed", _fake_resolve_seed(result, source_url))

    captured = {}

    async def fake_ingest_with_retry(session, payload, input_url_normalized):
        captured["payload"] = payload
        return {"slug": "x", "url": "/m/x", "created": True}

    monkeypatch.setattr(wo134, "_ingest_with_retry", fake_ingest_with_retry)

    row_result = await wo134.process_row(
        session=None, row=row, covered_gov_ids=set(), source_tag="test"
    )

    assert row_result.outcome == "ingested_tier1_2"
    assert captured["payload"]["gov_id"] == "test:wo222:0001"


async def test_process_row_omits_gov_id_when_row_gov_id_is_blank(monkeypatch):
    source_url = "https://wo222-b.granicus.com/MediaPlayer.php?view_id=1&clip_id=1"
    row = _wo134_row("", source_url)
    result = _segments_result(source_url)

    monkeypatch.setattr(
        wo134, "locate_platform_url", _fake_locate_platform_url(source_url)
    )
    monkeypatch.setattr(wo134, "resolve_seed", _fake_resolve_seed(result, source_url))

    captured = {}

    async def fake_ingest_with_retry(session, payload, input_url_normalized):
        captured["payload"] = payload
        return {"slug": "x", "url": "/m/x", "created": True}

    monkeypatch.setattr(wo134, "_ingest_with_retry", fake_ingest_with_retry)

    row_result = await wo134.process_row(
        session=None, row=row, covered_gov_ids=set(), source_tag="test"
    )

    assert row_result.outcome == "ingested_tier1_2"
    assert "gov_id" not in captured["payload"]


# --------------------------------------------------------------------------
# 1b. scripts/bulk_ingest.py's process_one()
# --------------------------------------------------------------------------


class _FakeBulkResult:
    platform = "granicus"
    segments = []
    agenda_items = []
    agenda_link = None
    video_url = "https://wo222-c.granicus.com/MediaPlayer.php?clip_id=9"
    title = "Test City Council Meeting"

    def model_dump(self):
        return {
            "platform": self.platform,
            "segments": self.segments,
            "agenda_items": self.agenda_items,
            "agenda_link": self.agenda_link,
            "video_url": self.video_url,
            "source_url": "https://wo222-c.granicus.com/view.php",
            "title": self.title,
        }


class _FakeBulkFinder:
    async def resolve(self, url):
        return _FakeBulkResult()


async def _run_process_one(monkeypatch, *, gov_id):
    import scripts.bulk_ingest as mod

    monkeypatch.setattr(mod, "detect_platform", lambda url: "granicus")
    monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeBulkFinder())

    captured = {}

    async def fake_ingest(session, payload, input_url_normalized, **kwargs):
        captured["payload"] = payload
        return {"slug": "x", "url": "/m/x", "created": True}

    monkeypatch.setattr(mod, "_ingest", fake_ingest)

    result = await mod.process_one(
        None,
        "https://wo222-c.granicus.com/view.php",
        dry_run=False,
        gov_id=gov_id,
    )
    assert result["status"] == "ingested"
    return captured["payload"]


async def test_bulk_ingest_process_one_sends_gov_id_when_given(monkeypatch):
    payload = await _run_process_one(monkeypatch, gov_id="test:wo222:0002")
    assert payload["gov_id"] == "test:wo222:0002"


async def test_bulk_ingest_process_one_omits_gov_id_when_not_given(monkeypatch):
    payload = await _run_process_one(monkeypatch, gov_id=None)
    assert "gov_id" not in payload


# --------------------------------------------------------------------------
# 1c. scripts/bulk_ingest.py's _read_urls()/_expand_urls() (the optional
#     tab-separated per-line gov_id and its --gov-id fallback)
# --------------------------------------------------------------------------


def test_read_urls_parses_optional_tab_separated_gov_id(tmp_path):
    import scripts.bulk_ingest as mod

    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://a.example.gov/meeting/1\ttest:wo222:aaa\n"
        "https://b.example.gov/meeting/2\n"
        "# a comment line, ignored\n"
        "\n"
        "https://c.example.gov/meeting/3\t \n",  # blank after the tab
        encoding="utf-8",
    )

    urls = mod._read_urls(str(urls_file))

    assert urls == [
        ("https://a.example.gov/meeting/1", "test:wo222:aaa"),
        ("https://b.example.gov/meeting/2", None),
        ("https://c.example.gov/meeting/3", None),
    ]


def test_expand_urls_carries_a_playlist_lines_gov_id_onto_every_video(monkeypatch):
    import scripts.bulk_ingest as mod

    monkeypatch.setattr(
        mod,
        "_expand_playlist",
        lambda playlist_id: [
            "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        ],
    )

    expanded = mod._expand_urls(
        [
            (
                "https://www.youtube.com/playlist?list=PLxyz",
                "test:wo222:playlist-gov",
            ),
            ("https://example.gov/meeting/1", None),
        ]
    )

    assert expanded == [
        ("https://www.youtube.com/watch?v=aaaaaaaaaaa", "test:wo222:playlist-gov"),
        ("https://www.youtube.com/watch?v=bbbbbbbbbbb", "test:wo222:playlist-gov"),
        ("https://example.gov/meeting/1", None),
    ]


# --------------------------------------------------------------------------
# 2. crud-level: a payload gov_id actually keys a page, and WO-215's
#    manual_override guard still holds.
# --------------------------------------------------------------------------


def _ingest_payload(source_url, *, gov_id=None, jurisdiction=None):
    body = {
        "platform": "youtube",
        "source_url": source_url,
        "external_id": None,
        "title": "Test City Council Meeting",
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "video_url": source_url,
        "video_format": "mp4",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    if gov_id:
        body["gov_id"] = gov_id
    return body


async def test_payload_gov_id_keys_a_new_page_on_a_multi_gov_host_with_no_pin():
    # www.youtube.com is a real MULTI_GOV_HOSTS host (app/utils/
    # gov_registry/registry.py) -- with NO tenant_overrides.csv pin for
    # this made-up video id, the resolver ladder alone would land this
    # on tier `blank` (gov_id `rtr:unknown:www.youtube.com`), exactly
    # the WO-210 gap this WO closes at the ingest-payload level.
    url = "https://www.youtube.com/watch?v=wo222test0001"
    result = await crud.ingest_resolution(_ingest_payload(url, gov_id=ALAMEDA_CA), url)
    page = await crud.get_page_by_slug(result["slug"])
    assert page["gov_id"] == ALAMEDA_CA
    assert page["jurisdiction_confidence"] == "pinned"


async def test_payload_gov_id_resupplied_on_reingest_does_not_downgrade_manual_override():
    # A page already carries a human's manual_override identity (WO-99's
    # POST /internal/jurisdiction/override, the real mechanism this
    # protects against, not a hand-set column). A later sweep re-ingest
    # that happens to send the SAME gov_id in its payload must not
    # downgrade the page's tier from manual_override to pinned -- that
    # is WO-215's guard (archive/db/crud.py's `_find_or_create_page()`,
    # the `page.jurisdiction_confidence != _MANUAL_OVERRIDE_CONFIDENCE`
    # checks).
    url = "https://www.youtube.com/watch?v=wo222test0002"
    first = await crud.ingest_resolution(_ingest_payload(url), url)
    page_id = first["page_id"]

    override = await crud.override_jurisdiction(
        ids={page_id}, gov_id=ALAMEDA_CA, dry_run=False
    )
    assert override["changed"]

    page = await crud.get_page_by_slug(first["slug"])
    assert page["gov_id"] == ALAMEDA_CA
    assert page["jurisdiction_confidence"] == "manual_override"

    # Re-ingest: same page (same source_url), payload now carries the
    # row's gov_id -- same id a sweep script would send per this WO.
    second = await crud.ingest_resolution(_ingest_payload(url, gov_id=ALAMEDA_CA), url)
    assert second["page_id"] == page_id

    page_after = await crud.get_page_by_slug(first["slug"])
    assert page_after["gov_id"] == ALAMEDA_CA
    assert page_after["jurisdiction_confidence"] == "manual_override"


async def test_payload_gov_id_conflicting_with_existing_page_raises_instead_of_overwriting():
    # Same manual_override setup as above, but this time the payload's
    # gov_id is a DIFFERENT real government -- must be refused
    # (GovernmentMismatch, archive/main.py's own 409), never silently
    # overwritten, whether the existing id came from a manual override
    # or anywhere else.
    url = "https://www.youtube.com/watch?v=wo222test0003"
    first = await crud.ingest_resolution(_ingest_payload(url), url)
    page_id = first["page_id"]

    override = await crud.override_jurisdiction(
        ids={page_id}, gov_id=ALAMEDA_CA, dry_run=False
    )
    assert override["changed"]

    with pytest.raises(crud.GovernmentMismatch) as excinfo:
        await crud.ingest_resolution(_ingest_payload(url, gov_id=APPLETON_WI), url)
    assert excinfo.value.existing_gov_id == ALAMEDA_CA
    assert excinfo.value.supplied_gov_id == APPLETON_WI

    # Untouched: still the human's original manual_override identity.
    page_after = await crud.get_page_by_slug(first["slug"])
    assert page_after["gov_id"] == ALAMEDA_CA
    assert page_after["jurisdiction_confidence"] == "manual_override"
