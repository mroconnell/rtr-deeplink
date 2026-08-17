"""VideoObject structured-data additions on /m/{slug}: thumbnailUrl (+
og:image/twitter:card) for YouTube-backed pages, and Clip "key moments"
built from agenda_items -- see BACKLOG.md's Google Search Console entry
(missing thumbnailUrl blocks video rich-result eligibility) and
CLAUDE_BACKLOG.md's SEO tier-1 items this implements.

Synthetic pages built via crud.ingest_resolution(), same pattern as
test_accounts_anonymous_regression.py: the payload mirrors a real
resolver push, the YouTube embed URL is the exact shape youtube.py
builds (`https://www.youtube.com/embed/{11-char id}`), and agenda_items
use the real {start, end, text} TranscriptSegment shape every adapter
produces. Synthetic because the thing under test is template rendering
logic, not adapter parsing -- the shapes themselves are all
fixture-confirmed elsewhere.
"""

import json
import re

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.utils.video_thumbnail import youtube_thumbnail_url

archive_client = TestClient(archive.main.app)

_JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', re.DOTALL
)


def _payload(external_id: str, source_url: str, **overrides) -> dict:
    payload = {
        "platform": "youtube",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Structured Data Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Fresno, CA",
        "video_url": "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "video_format": "youtube",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


async def _make_page(external_id: str, **overrides) -> str:
    url = f"https://example.com/structured-data/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, **overrides), url)
    return result["slug"]


def _get_json_ld(html: str) -> dict:
    """Extract and parse the page's VideoObject JSON-LD -- json.loads
    doubles as the validity check for the template's hand-built JSON
    (trailing commas / unquoted values would fail here)."""
    match = _JSON_LD_RE.search(html)
    assert match, "no JSON-LD script block found"
    return json.loads(match.group(1))


# --- youtube_thumbnail_url() itself -------------------------------------


def test_thumbnail_from_embed_url():
    # The exact video_url shape youtube.py builds (its line ~76).
    assert (
        youtube_thumbnail_url("https://www.youtube.com/embed/dQw4w9WgXcQ")
        == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    )


def test_thumbnail_from_watch_and_short_urls():
    assert (
        youtube_thumbnail_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    )
    assert (
        youtube_thumbnail_url("https://youtu.be/dQw4w9WgXcQ")
        == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    )


def test_thumbnail_none_for_non_youtube_or_missing():
    assert youtube_thumbnail_url("https://example.granicus.com/video.m3u8") is None
    assert youtube_thumbnail_url(None) is None
    assert youtube_thumbnail_url("") is None


# --- rendered /m/{slug} pages -------------------------------------------


async def test_youtube_page_gets_thumbnail_and_clips(monkeypatch):
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page(
        "sd-youtube-clips",
        agenda_items=[
            {"start": 0.0, "end": 754.0, "text": "Call to Order and Roll Call"},
            {"start": 754.0, "end": 2130.5, "text": "Public Comment"},
            {"start": 2130.5, "end": 2130.5, "text": "Adjournment"},
        ],
    )

    response = archive_client.get(f"/m/{slug}")
    assert response.status_code == 200

    data = _get_json_ld(response.text)
    assert data["@type"] == "VideoObject"
    assert data["thumbnailUrl"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert data["embedUrl"] == "https://www.youtube.com/embed/dQw4w9WgXcQ"

    clips = data["hasPart"]
    assert [c["@type"] for c in clips] == ["Clip", "Clip", "Clip"]
    assert clips[0]["name"] == "Call to Order and Roll Call"
    assert clips[0]["startOffset"] == 0
    assert clips[0]["endOffset"] == 754
    assert clips[1]["url"] == f"https://example.org/m/{slug}?t=754"
    # end == start (the Adjournment item): endOffset suppressed, not
    # emitted as a zero-length clip.
    assert clips[2]["startOffset"] == 2130
    assert "endOffset" not in clips[2]

    assert (
        '<meta property="og:image" content="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg">'
        in response.text
    )
    assert '<meta name="twitter:card" content="summary_large_image">' in response.text


async def test_unreliable_timestamps_suppress_clips_only(monkeypatch):
    # Several CivicClerk cities report every eventBookmark at the same
    # instant (the agenda section's own unreliable_timestamps guard, which
    # the Clip guard mirrors) -- key moments claiming 3 items all start at
    # 0:00 would be false navigation, so hasPart must be absent while the
    # rest of the VideoObject stays intact.
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page(
        "sd-unreliable-ts",
        agenda_items=[
            {"start": 0.0, "end": 0.0, "text": "Item One"},
            {"start": 0.0, "end": 0.0, "text": "Item Two"},
            {"start": 0.0, "end": 0.0, "text": "Item Three"},
        ],
    )

    response = archive_client.get(f"/m/{slug}")
    data = _get_json_ld(response.text)
    assert "hasPart" not in data
    assert data["thumbnailUrl"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


async def test_no_clips_without_public_base_url(monkeypatch):
    # Locally (no PUBLIC_BASE_URL) there's no absolute URL to build Clip
    # links from -- same reason canonical/og:url are skipped. hasPart must
    # be absent, and the JSON must still parse.
    monkeypatch.setitem(archive.main.templates.env.globals, "public_base_url", "")
    slug = await _make_page(
        "sd-no-base-url",
        agenda_items=[
            {"start": 0.0, "end": 60.0, "text": "Item One"},
            {"start": 60.0, "end": 120.0, "text": "Item Two"},
        ],
    )

    response = archive_client.get(f"/m/{slug}")
    data = _get_json_ld(response.text)
    assert "hasPart" not in data
    assert "url" not in data


async def test_m3u8_page_has_no_thumbnail_but_valid_json(monkeypatch):
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page(
        "sd-m3u8-page",
        platform="granicus",
        video_url="https://archive-media.granicus.com/OnDemand/x/x.m3u8",
        video_format="m3u8",
        agenda_items=[
            {"start": 0.0, "end": 60.0, "text": "Item One"},
            {"start": 60.0, "end": 120.0, "text": "Item Two"},
        ],
    )

    response = archive_client.get(f"/m/{slug}")
    data = _get_json_ld(response.text)
    assert "thumbnailUrl" not in data
    assert data["contentUrl"] == "https://archive-media.granicus.com/OnDemand/x/x.m3u8"
    # Clips don't depend on the thumbnail -- an m3u8 page with real
    # timestamps still gets key moments.
    assert len(data["hasPart"]) == 2
    assert '<meta property="og:image"' not in response.text


async def test_html_in_item_text_stripped_from_clip_name(monkeypatch):
    # Synthetic, but the shape is real and was found live, not assumed:
    # Minneapolis LIMS stores raw HTML anchors inside agenda item text
    # (confirmed 2026-08-14 on the production page
    # /m/city-of-minneapolis-mn-2026-08-10-committee-of-the-whole, whose
    # Clip names leaked markup before this fix -- the adapter-side root
    # cause is tracked in BACKLOG.md). A schema.org name must be plain
    # text regardless of what the source stored.
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page(
        "sd-html-in-name",
        agenda_items=[
            {"start": 0.0, "end": 60.0, "text": "Item One"},
            {
                "start": 122.0,
                "end": 310.0,
                "text": "<a href='/Download/CommitteeReport/4915/x.pdf' class='previousmettingdate'>8/4/2026</a> Committee Report",
            },
        ],
    )

    response = archive_client.get(f"/m/{slug}")
    data = _get_json_ld(response.text)
    name = data["hasPart"][1]["name"]
    assert "<" not in name and "href" not in name
    assert "8/4/2026" in name and "Committee Report" in name


async def test_long_item_text_truncated_in_clip_name(monkeypatch):
    # IQM2 agenda items can carry full ordinance/resolution text -- a
    # "key moment" label should stay label-sized.
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    long_text = "An ordinance amending the zoning code " * 20
    slug = await _make_page(
        "sd-long-name",
        agenda_items=[
            {"start": 0.0, "end": 60.0, "text": "Item One"},
            {"start": 60.0, "end": 120.0, "text": long_text},
        ],
    )

    response = archive_client.get(f"/m/{slug}")
    data = _get_json_ld(response.text)
    assert len(data["hasPart"][1]["name"]) <= 103  # 100 + ellipsis
