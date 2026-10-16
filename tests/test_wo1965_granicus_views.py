"""WO-1965: stored Granicus `view_id`s (`granicus_views.csv`), the two
places that read them, and `scripts/probe_granicus_view_ids.py`.

The feed parser tests run on real Granicus video RSS feeds saved in
`tests/fixtures/`. Everything that needs a network answer (the probe loop,
robots, the resolver's listing) uses a fake fetcher or a monkeypatched
lister: these are SYNTHETIC, since this repo's cloud sessions get a 403
from granicus.com and the probe has not yet been run live (it runs from
the office Mac).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.platforms import granicus
from app.platforms.base import CalendarPageError
from app.platforms.resolving.fetch import FetchResult
from scripts import probe_granicus_view_ids as probe

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def views_file(tmp_path, monkeypatch):
    path = tmp_path / "granicus_views.csv"
    monkeypatch.setattr(granicus, "GRANICUS_VIEWS_FILE", path)
    granicus.known_granicus_views.cache_clear()
    yield path
    granicus.known_granicus_views.cache_clear()


def _write(path: Path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=probe.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _row(host, view_id, title=""):
    return {
        "host": host,
        "view_id": str(view_id),
        "channel_title": title,
        "evidence": "test",
        "checked": "2026-10-16",
    }


# --- the shipped file ------------------------------------------------------


def test_shipped_file_rows_each_match_a_real_saved_feed():
    """Every seed row cites a saved real feed whose own source URL names the
    same host and view_id."""
    granicus.known_granicus_views.cache_clear()
    with granicus.GRANICUS_VIEWS_FILE.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows
    for row in rows:
        fixture = row["evidence"].split("saved as ", 1)[1].split(" ", 1)[0]
        xml = (Path(__file__).parent.parent / fixture).read_text()
        assert (
            f"https://{row['host']}/ViewPublisherRSS.php?view_id={row['view_id']}"
            f"&amp;mode=video" in xml
        )
        assert (row["view_id"], row["channel_title"]) in (
            granicus.known_granicus_views_for(row["host"])
        )


# --- loader ----------------------------------------------------------------


def test_loader_normalizes_host_and_drops_repeats(views_file):
    _write(
        views_file,
        [
            _row("Nevco.Granicus.com", 2, "Nevada City Council"),
            _row("nevco.granicus.com", 4, "Grass Valley City Council"),
            _row("nevco.granicus.com", 4, "duplicate"),
            _row("bad.granicus.com", "x"),
        ],
    )
    assert granicus.known_granicus_views_for("www.nevco.granicus.com:443") == [
        ("2", "Nevada City Council"),
        ("4", "Grass Valley City Council"),
    ]
    assert granicus.known_granicus_views_for("bad.granicus.com") == []
    assert granicus.known_granicus_views_for("other.granicus.com") == []


def test_missing_file_means_no_views(views_file):
    assert granicus.known_granicus_views() == {}


# --- granicus.py: a pasted bare host ---------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://tenant.granicus.com",
        "https://tenant.granicus.com/",
        "https://tenant.granicus.com/ViewPublisher.php",
        "https://www.tenant.granicus.com/ViewPublisherRSS.php?mode=video",
    ],
)
def test_bare_host_maps_to_stored_hub(views_file, url):
    _write(views_file, [_row("tenant.granicus.com", 47)])
    assert granicus.stored_view_urls_for_bare_host(url) == [
        "https://tenant.granicus.com/ViewPublisher.php?view_id=47"
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://tenant.granicus.com/ViewPublisher.php?view_id=3",
        "https://tenant.granicus.com/MediaPlayer.php?view_id=3&clip_id=9",
        "https://tenant.granicus.com/player/clip/7460",
        "https://unknown.granicus.com/",
    ],
)
def test_non_bare_or_unknown_host_is_left_alone(views_file, url):
    _write(views_file, [_row("tenant.granicus.com", 47)])
    assert granicus.stored_view_urls_for_bare_host(url) == []


@pytest.mark.asyncio
async def test_resolve_bare_host_lists_stored_views_newest_first(
    views_file, monkeypatch
):
    # Synthetic: the RSS answers are monkeypatched, not fetched.
    _write(
        views_file, [_row("tenant.granicus.com", 2), _row("tenant.granicus.com", 47)]
    )
    feeds = {
        "2": [{"title": "A", "date": "2026-01-05", "url": "u1"}],
        "47": [
            {"title": "B", "date": "2026-09-01", "url": "u2"},
            {"title": "A again", "date": "2026-01-05", "url": "u1"},
        ],
    }
    calls = []

    async def fake_list_hub_meetings(url, *, limit=15):
        calls.append(url)
        return feeds[url.rsplit("=", 1)[1]]

    monkeypatch.setattr(granicus, "list_hub_meetings", fake_list_hub_meetings)
    with pytest.raises(CalendarPageError) as exc:
        await granicus.GranicusAssetFinder().resolve("https://tenant.granicus.com/")
    assert [c["url"] for c in exc.value.candidates] == ["u2", "u1"]
    assert calls == [
        "https://tenant.granicus.com/ViewPublisher.php?view_id=2",
        "https://tenant.granicus.com/ViewPublisher.php?view_id=47",
    ]


# --- Meeting Finder: stored view before the live 1-6 probe -----------------


class _NoFetch:
    async def fetch(self, url, need_links=False):  # pragma: no cover
        raise AssertionError(f"stored view should need no fetch, got {url}")


@pytest.mark.asyncio
async def test_listing_uses_stored_view_without_fetching(views_file):
    from app.platforms.meeting_finder import listing

    _write(
        views_file,
        [
            _row("nevco.granicus.com", 2, "Nevada City Council"),
            _row("nevco.granicus.com", 47, "Grass Valley City Council"),
        ],
    )
    assert (
        await listing._granicus_discover_view_id(
            "https://nevco.granicus.com/", _NoFetch(), gov_name="Grass Valley city"
        )
        == "https://nevco.granicus.com/ViewPublisher.php?view_id=47"
    )
    assert (
        await listing._granicus_discover_view_id(
            "https://nevco.granicus.com/", _NoFetch()
        )
        == "https://nevco.granicus.com/ViewPublisher.php?view_id=2"
    )


# --- probe script: feed parser on real saved feeds -------------------------


@pytest.mark.parametrize(
    "fixture,host,view_id,title,clips,newest",
    [
        (
            "granicus/tulsa_view4_rss_clip7694.xml",
            "tulsa-ok.granicus.com",
            4,
            "City of Tulsa, OK: TGOV - Tulsa Government Access Television",
            1,
            "2026-08-05",
        ),
        (
            "granicus_channel/kansascity_viewpublisher_rss.xml",
            "kansascity.granicus.com",
            2,
            "City of Kansas City: Video on Demand: Meetings",
            None,
            None,
        ),
        (
            "granicus/pwcva_view23_rss_video.xml",
            "pwcgov.granicus.com",
            23,
            "Prince William County, Virginia: Streaming Media Archive2",
            None,
            None,
        ),
    ],
)
def test_parse_video_feed_on_real_feeds(fixture, host, view_id, title, clips, newest):
    xml = (FIXTURES / fixture).read_text()
    found = probe.parse_video_feed(xml, host, view_id)
    assert found is not None
    assert found.channel_title == title
    assert found.clip_count == len(
        granicus._parse_rss_items(xml, host, str(view_id), 10_000)
    )
    assert found.clip_count >= 1
    if clips is not None:
        assert found.clip_count == clips
    if newest is not None:
        assert found.newest_date == newest
    assert "clip item(s)" in found.evidence()


def test_parse_video_feed_rejects_empty_and_no_video():
    # Synthetic shapes, cut down from the real feed structure above.
    assert (
        probe.parse_video_feed("<rss><channel><title>x</title></channel></rss>", "h", 1)
        is None
    )
    assert (
        probe.parse_video_feed(
            "<rss><channel><title>x</title><item><title>(No Video)</title>"
            "<link>https://h/MediaPlayer.php?view_id=1&amp;clip_id=5</link></item>"
            "</channel></rss>",
            "h",
            1,
        )
        is None
    )
    assert probe.parse_video_feed("", "h", 1) is None


def test_parse_ids_and_hosts(tmp_path):
    assert probe.parse_ids("1-3,44-45,2") == [1, 2, 3, 44, 45]
    hosts_file = tmp_path / "hosts.txt"
    hosts_file.write_text(
        "# comment\nhttps://www.Tacoma.granicus.com/ViewPublisher.php\n\n"
        "tacoma.granicus.com\nnevco.granicus.com # shared\n"
    )
    assert probe.read_hosts(["alpha.granicus.com"], hosts_file) == [
        "alpha.granicus.com",
        "tacoma.granicus.com",
        "nevco.granicus.com",
    ]


# --- probe script: the loop (synthetic fake fetcher) ------------------------


def _result(url, *, status=200, html="", final_url=None, outcome=None, challenge=False):
    return FetchResult(
        requested_url=url,
        final_url=final_url or url,
        status=status,
        html=html,
        access_mode="plain",
        outcome=outcome,
        challenge=challenge,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )


class _FakeFetcher:
    def __init__(self, answers):
        self.answers = answers
        self.urls = []

    async def fetch(self, url, need_links=False):
        self.urls.append(url)
        view_id = int(url.split("view_id=")[1].split("&")[0])
        return self.answers(url, view_id)


@pytest.mark.asyncio
async def test_probe_host_finds_every_populated_id_and_ignores_redirects():
    tulsa = (FIXTURES / "granicus/tulsa_view4_rss_clip7694.xml").read_text()

    def answers(url, view_id):
        if view_id in (4, 47):
            return _result(url, html=tulsa)
        if view_id == 5:
            # Redirected to the tenant's home page: not a feed.
            return _result(url, html=tulsa, final_url="https://t.granicus.com/")
        return _result(url, status=404)

    fetcher = _FakeFetcher(answers)
    found, note = await probe.probe_host(
        "t.granicus.com", probe.parse_ids("1-60"), fetcher
    )
    assert [v.view_id for v in found] == [4, 47]
    assert note == ""
    assert len(fetcher.urls) == 60
    assert all("mode=video" in u and "ViewPublisherRSS.php" in u for u in fetcher.urls)


@pytest.mark.asyncio
async def test_probe_host_gives_up_after_three_blocks_in_a_row():
    def answers(url, view_id):
        return _result(url, status=403, outcome="blocked-browser-headers")

    fetcher = _FakeFetcher(answers)
    found, note = await probe.probe_host("gated.granicus.com", range(1, 61), fetcher)
    assert found == []
    assert "blocked 3 times" in note
    assert len(fetcher.urls) == 3


# --- probe script: writing ---------------------------------------------------


def test_append_rows_adds_only_new_pairs(tmp_path):
    path = tmp_path / "granicus_views.csv"
    _write(path, [_row("a.granicus.com", 4, "A")])
    views = [
        probe.FoundView("a.granicus.com", 4, "A", 3, "2026-10-01"),
        probe.FoundView("a.granicus.com", 47, "A two", 2, None),
        probe.FoundView("b.granicus.com", 1, 'Title, with "quotes"', 1, "2026-09-09"),
    ]
    assert probe.append_rows(path, views, "2026-10-16") == 2
    assert probe.append_rows(path, views, "2026-10-17") == 0
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["host"], r["view_id"]) for r in rows] == [
        ("a.granicus.com", "4"),
        ("a.granicus.com", "47"),
        ("b.granicus.com", "1"),
    ]
    assert rows[2]["channel_title"] == 'Title, with "quotes"'
    assert rows[1]["checked"] == "2026-10-16"


def test_append_rows_creates_file_with_header(tmp_path):
    path = tmp_path / "new.csv"
    assert (
        probe.append_rows(
            path, [probe.FoundView("c.granicus.com", 9, "C", 1, None)], "d"
        )
        == 1
    )
    assert path.read_text().splitlines()[0] == ",".join(probe.CSV_FIELDS)


@pytest.mark.asyncio
async def test_dry_run_writes_nothing_and_skips_robots_disallowed(
    tmp_path, monkeypatch
):
    # Synthetic: robots and the probe are monkeypatched; no network.
    path = tmp_path / "views.csv"
    _write(path, [_row("stored.granicus.com", 1)])

    async def fake_robots(host):
        if host == "blocked.granicus.com":
            return False, None, "robots.txt disallows /ViewPublisherRSS.php (/)"
        return True, None, ""

    probed = []

    async def fake_probe_host(host, ids, fetcher):
        probed.append(host)
        return [probe.FoundView(host, 44, "T", 1, None)], ""

    monkeypatch.setattr(probe, "check_robots", fake_robots)
    monkeypatch.setattr(probe, "probe_host", fake_probe_host)
    args = probe.build_parser().parse_args(
        ["stored.granicus.com", "blocked.granicus.com", "new.granicus.com",
         "--views-file", str(path)]
    )  # fmt: skip
    assert await probe.run(args) == 0
    assert probed == ["new.granicus.com"]
    assert len(path.read_text().splitlines()) == 2

    args = probe.build_parser().parse_args(
        ["new.granicus.com", "--views-file", str(path), "--write"]
    )
    assert await probe.run(args) == 0
    assert path.read_text().splitlines()[-1].startswith("new.granicus.com,44,T,")
