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


async def test_m3u8_page_has_no_thumbnail_until_a_frame_is_extracted(monkeypatch):
    # Rewritten for WO-28 (2026-08-21): this test used to encode "m3u8
    # pages never have a thumbnail" as the expected end state. That's no
    # longer true -- they get a real extracted frame -- but the
    # *imageless* state is still real and still has to render correctly,
    # because it's what every page looks like between being archived and
    # its first frame landing, and permanently for a page whose source
    # media is unreachable. See the companion test below for the
    # after-extraction half.
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
    # ...but a twitter:card is still emitted (fixed 2026-08-21): it used to
    # live inside the thumbnail guard, so every non-YouTube page -- the
    # majority of the Archive -- shipped none at all. "summary", not
    # "summary_large_image", since there's no image to make large.
    assert '<meta name="twitter:card" content="summary">' in response.text


async def test_m3u8_page_advertises_its_card_once_a_frame_exists(monkeypatch):
    # The WO-28 half: an extracted frame turns the same page into a
    # thumbnail-bearing, large-image-card page. og:image, the VideoObject
    # thumbnailUrl (the ONLY critical issue a real 2026-08-21 Search
    # Console URL Inspection reported on the San Carlos page) and the
    # Event image all point at the one card URL.
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page(
        "sd-m3u8-with-card",
        platform="granicus",
        video_url="https://archive-media.granicus.com/OnDemand/y/y.m3u8",
        video_format="m3u8",
    )
    page = await crud.get_page_by_slug(slug)
    await crud.store_thumbnail(
        page["id"],
        offset_seconds=15381,
        image_bytes=b"\xff\xd8\xff\xd9",
        etag="9" * 64,
        is_default=True,
    )

    response = archive_client.get(f"/m/{slug}")
    expected = f"https://example.org/m/{slug}/card.jpg"
    data = _get_json_ld(response.text)
    assert data["thumbnailUrl"] == expected
    assert f'<meta property="og:image" content="{expected}">' in response.text
    assert '<meta name="twitter:card" content="summary_large_image">' in response.text
    # Event JSON-LD (the second ld+json block) gets the same image.
    assert response.text.count(expected) >= 3


async def test_card_url_carries_the_visitors_own_timestamp(monkeypatch):
    # A shared deep link's card should show the moment that was shared,
    # so ?t= passes straight through to the card URL. The "+20s so the
    # frame lands inside the content rather than on the transition into
    # it" lead is applied by the card route, not baked into the markup --
    # which keeps the advertised URL identical to the link that was
    # shared.
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page(
        "sd-m3u8-card-t",
        platform="granicus",
        video_url="https://archive-media.granicus.com/OnDemand/z/z.m3u8",
        video_format="m3u8",
    )
    page = await crud.get_page_by_slug(slug)
    await crud.store_thumbnail(
        page["id"],
        offset_seconds=15381,
        image_bytes=b"\xff\xd8\xff\xd9",
        etag="8" * 64,
        is_default=True,
    )

    response = archive_client.get(f"/m/{slug}?t=982")
    assert (
        f'<meta property="og:image" content="https://example.org/m/{slug}/card.jpg?t=982">'
        in response.text
    )
    # A nonsense/negative timestamp is ignored rather than propagated.
    plain = archive_client.get(f"/m/{slug}?t=-5")
    assert (
        f'<meta property="og:image" content="https://example.org/m/{slug}/card.jpg">'
        in plain.text
    )


async def test_shared_start_run_gets_end_offsets(monkeypatch):
    # The real San Carlos consent-calendar block, rendered end to end:
    # twelve items sharing one IQM2 timestamp used to emit twelve
    # "Missing field endOffset" warnings. See archive/utils/clips.py.
    monkeypatch.setitem(
        archive.main.templates.env.globals, "public_base_url", "https://example.org"
    )
    slug = await _make_page(
        "sd-consent-run",
        agenda_items=[
            {"start": 982.0, "end": 982.0, "text": f"Consent item {i}"}
            for i in range(12)
        ]
        + [{"start": 1056.0, "end": 1400.0, "text": "Public Hearing"}],
    )

    clips = _get_json_ld(archive_client.get(f"/m/{slug}").text)["hasPart"]
    assert len(clips) == 13
    assert all(clip["endOffset"] == 1056 for clip in clips[:12])
    assert clips[12]["endOffset"] == 1400


async def test_twitter_card_summary_when_no_image_at_all():
    # A page with no video at all (so no thumbnail, and no VideoObject
    # block either) still gets a card type -- the fix is not scoped to
    # "has a video but no thumbnail".
    slug = await _make_page(
        "sd-no-video-card",
        platform="granicus",
        video_url=None,
        video_format=None,
    )

    response = archive_client.get(f"/m/{slug}")
    assert response.status_code == 200
    assert '<meta name="twitter:card" content="summary">' in response.text
    assert "summary_large_image" not in response.text


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


# --- meeting-date markup + validation ------------------------------------
#
# Synthetic in the same sense as everything above (rendering logic, not
# adapter parsing), but the malformed-date shapes below are deliberately
# NOT invented failure modes: `date` is an unvalidated free string end to
# end (Optional[str] on ResolvedMeeting and IngestRequest, String(20) as a
# column), so nothing between an adapter and the template would reject
# one. What's still unconfirmed is whether any *real* production row holds
# one -- that's exactly what /internal/date-format-audit exists to answer;
# see BACKLOG.md's Search Console entry.


def test_meeting_date_html_wraps_valid_date():
    assert (
        archive.main.meeting_date_html("2026-01-01")
        == '<time datetime="2026-01-01">2026-01-01</time>'
    )


def test_meeting_date_html_normalizes_datetime_shaped_value():
    # A stored "YYYY-MM-DDTHH:MM:SS" still gets a valid datetime attribute
    # (normalized), with the visible text left exactly as stored.
    assert (
        archive.main.meeting_date_html("2026-01-01T00:00:00")
        == '<time datetime="2026-01-01">2026-01-01T00:00:00</time>'
    )


def test_meeting_date_html_falls_back_to_plain_escaped_text():
    # An invalid `datetime` attribute is worse than no <time> element, so
    # an unparseable date renders as plain text -- escaped, since this
    # filter returns Markup.
    assert archive.main.meeting_date_html("TBD") == "TBD"
    assert archive.main.meeting_date_html(None) == ""
    assert "<" not in archive.main.meeting_date_html("<b>x</b>")


async def test_page_renders_semantic_time_and_valid_upload_date():
    slug = await _make_page("sd-time-markup")

    response = archive_client.get(f"/m/{slug}")
    assert '<time datetime="2026-01-01">2026-01-01</time>' in response.text
    data = _get_json_ld(response.text)
    assert data["uploadDate"] == "2026-01-01T00:00:00Z"


async def test_unparseable_date_emits_no_upload_date_and_no_time_element():
    # The directly-fixable half of Search Console's `uploadDate` "invalid
    # datetime value" flag: this used to interpolate the stored string
    # verbatim, producing "Meeting cancelledT00:00:00Z" in the JSON-LD.
    slug = await _make_page("sd-bad-date", date="Meeting cancelled")

    response = archive_client.get(f"/m/{slug}")
    assert response.status_code == 200
    assert "<time" not in response.text
    assert "Meeting cancelled" in response.text  # still shown to a human
    data = _get_json_ld(response.text)
    assert "uploadDate" not in data
    # ...and the Event block's startDate is gated the same way.
    events = [
        json.loads(m)
        for m in re.findall(
            r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>',
            response.text,
            re.DOTALL,
        )
    ]
    event = next(e for e in events if e["@type"] == "Event")
    assert "startDate" not in event


async def test_date_format_audit_buckets_by_shape():
    await _make_page("sd-audit-clean", date="2026-02-02")
    await _make_page("sd-audit-non-iso", date="2026-02-03T00:00:00")
    await _make_page("sd-audit-bad", date="not a date")
    await _make_page("sd-audit-null", date=None)

    result = await crud.get_meeting_date_format_audit()
    shapes = result["by_shape"]
    # Other tests in this module create pages too, so assert on this
    # module's own rows rather than exact archive-wide totals.
    assert shapes["iso_date"] >= 1
    assert shapes["parseable_non_iso"] >= 1
    assert shapes["unparseable"] >= 1
    assert shapes["null"] >= 1

    # Keyed on the stored value, not the slug: crud._find_or_create_page()
    # derives a slug from jurisdiction/date/title, not from external_id.
    by_stored = {r["stored_date"]: r for r in result["suspect_rows"]}
    non_iso = by_stored["2026-02-03T00:00:00"]
    assert non_iso["bucket"] == "parseable_non_iso"
    assert non_iso["normalized_date"] == "2026-02-03"
    assert non_iso["slug"]
    bad = by_stored["not a date"]
    assert bad["bucket"] == "unparseable"
    assert bad["normalized_date"] is None
    # Clean and null rows are never listed -- the audit's whole point is a
    # short response naming only what's actually suspect.
    assert "2026-02-02" not in by_stored
    assert None not in by_stored
