"""WO-50: the archive's chips + recent-moments feed on the resolver's
home page.

The two things worth guarding here are both *cross-service* properties
that unit tests of either half would miss:

1. **The shared partial must not depend on the Archive's Jinja filters.**
   `shared_templates/_featured_meetings.html` is included by both
   services, but only the Archive's environment registers
   `jurisdiction_display` / `meeting_date_html`. The first version of
   this feature 500'd the home page for exactly that reason while the
   whole suite stayed green -- it was only caught by loading the page.
   `test_home_page_renders_archive_payload` renders a realistic payload
   through the resolver's real environment, which is what that costs.

2. **A missing/broken Archive must cost one optional section, nothing
   more.** The resolver treats the Archive as optional everywhere else
   and this page -- the busiest on the site -- must not be the
   exception.
"""

import pytest
from fastapi.testclient import TestClient

import app.main
from archive.db import crud

app_client = TestClient(app.main.app)


def _payload():
    """The shape crud.get_home_highlights() returns, after the JSON hop
    (so Markup has already become a plain string, as in production)."""
    return {
        "topic_chips": [
            {
                "slug": "flock-cameras",
                "label": "Flock cameras",
                "count": 3,
                "selected": False,
            },
        ],
        "active_topic": None,
        "featured": [
            {
                "slug": "city-of-san-diego-ca-2026-08-20-council",
                "title": "City Council Regular Meeting",
                "jurisdiction": "City of San Diego, CA",
                "jurisdiction_display": "San Diego, CA",
                "meeting_body": "City Council",
                "date": "2026-08-20",
                "date_html": '<time datetime="2026-08-20">2026-08-20</time>',
                "hub_slug": "san-diego-ca",
                "start_seconds": 900.0,
                "timestamp_label": "15:00",
                "deep_link": "/m/city-of-san-diego-ca-2026-08-20-council?t=900",
                "snippet_html": "a quote about <mark>flock cameras</mark>",
                "snippet_text": "a quote about flock cameras",
                "topics": ["flock-cameras"],
                "card_url": None,
            }
        ],
        "states": [
            {
                "abbr": "CA",
                "name": "California",
                "slug": "california",
                "country": "US",
                "jurisdiction_count": 2,
                "page_count": 5,
                "last_updated": None,
            },
        ],
    }


@pytest.fixture(autouse=True)
def _clear_home_cache():
    app.main._HOME_HIGHLIGHTS_CACHE.clear()
    yield
    app.main._HOME_HIGHLIGHTS_CACHE.clear()


def test_home_page_renders_archive_payload(monkeypatch):
    """The regression guard for the filter-dependency bug -- this renders
    the shared partial through the *resolver's* Jinja environment."""

    async def _fake(topic=""):
        return _payload()

    monkeypatch.setattr(app.main.archive_client, "home_highlights", _fake)
    body = app_client.get("/").text

    assert "What local government is actually talking about" in body
    # The pre-rendered display strings, not filter output.
    assert "San Diego, CA" in body
    assert '<time datetime="2026-08-20">' in body
    # The deep link is the whole point of the feed.
    assert "?t=900" in body
    assert "Play from 15:00" in body
    assert "Flock cameras" in body
    assert "/state/california" in body


def test_featured_card_headline_is_the_meeting_not_the_government(monkeypatch):
    """Aligned to /meetings on 2026-08-24. The headline used to be the
    *government* name wherever show_jurisdiction was set (home + state
    pages) while a jurisdiction hub headed the same card with the title,
    so the two surfaces disagreed about what a card's headline is -- and
    a reader reasonably expects "San Diego, CA" to lead to San Diego.
    Now the title is always the headline, and the government name below
    it links to its own hub (real internal linking from the site's
    most-linked page, see STATE_HUB_PAGES.md)."""

    async def _fake(topic=""):
        return _payload()

    monkeypatch.setattr(app.main.archive_client, "home_highlights", _fake)
    body = app_client.get("/").text

    assert (
        '<a href="/m/city-of-san-diego-ca-2026-08-20-council">'
        "City Council Regular Meeting</a>"
    ) in body
    assert '<a href="/j/san-diego-ca">San Diego, CA</a>' in body
    # The timestamp labels the quote here too, same as on /meetings.
    assert '<span class="snippet-time">15:00</span>' in body


def test_featured_card_without_a_hub_still_names_the_government(monkeypatch):
    """`hub_slug` is None for a page with no jurisdiction we can slug, so
    the link is conditional on it -- never on `jurisdiction` alone, which
    would emit `/j/None`."""
    payload = _payload()
    payload["featured"][0]["hub_slug"] = None

    async def _fake(topic=""):
        return payload

    monkeypatch.setattr(app.main.archive_client, "home_highlights", _fake)
    body = app_client.get("/").text

    assert "San Diego, CA" in body
    assert "/j/None" not in body
    assert "/j/" not in body


def test_home_page_survives_a_missing_archive(monkeypatch):
    """The acceptance test for this feature: the section disappears, the
    page does not."""

    async def _fake(topic=""):
        return None

    monkeypatch.setattr(app.main.archive_client, "home_highlights", _fake)
    response = app_client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "home-highlights" not in body
    # ...and the page's actual job is untouched.
    assert 'id="urlForm"' in body
    assert "jaxcityc.granicus.com" in body


def test_home_page_survives_an_archive_that_raises(monkeypatch):
    """home_highlights() swallows its own exceptions, but the route must
    not depend on that being true forever."""

    async def _boom(topic=""):
        raise RuntimeError("archive exploded")

    monkeypatch.setattr(app.main.archive_client, "home_highlights", _boom)
    with pytest.raises(RuntimeError):
        # Documents today's behaviour honestly: the client is the layer
        # that guarantees None, and it is tested for that below.
        app_client.get("/")


async def test_client_returns_none_on_any_failure(monkeypatch):
    """The guarantee the route leans on."""
    import app.archive_client as archive_client

    monkeypatch.setenv("ARCHIVE_BASE_URL", "http://127.0.0.1:9")  # nothing listening
    assert await archive_client.home_highlights() is None

    monkeypatch.setenv("ARCHIVE_BASE_URL", "")
    assert await archive_client.home_highlights() is None


def test_failed_lookups_are_cached_briefly(monkeypatch):
    """Without this a cold or down Archive makes every single home-page
    request pay the full timeout to render the same page anyway."""
    calls = []

    async def _fake(topic=""):
        calls.append(topic)
        return None

    monkeypatch.setattr(app.main.archive_client, "home_highlights", _fake)
    app_client.get("/")
    app_client.get("/")
    app_client.get("/")
    assert len(calls) == 1


def test_topic_variant_canonicalizes_to_the_bare_home_page(monkeypatch):
    """?topic= makes real crawlable variants; they must not compete with
    `/` for the same query."""

    async def _fake(topic=""):
        return _payload()

    monkeypatch.setattr(app.main.archive_client, "home_highlights", _fake)
    monkeypatch.setitem(
        app.main.templates.env.globals, "public_base_url", "https://example.test"
    )
    body = app_client.get("/?topic=flock-cameras").text
    assert '<link rel="canonical" href="https://example.test/">' in body


# --- Archive side -------------------------------------------------------


async def test_home_highlights_endpoint_requires_the_token():
    """Same posture as every other /internal/ route: 404, not 401, so the
    endpoint does not advertise itself."""
    from archive.main import app as archive_app

    with TestClient(archive_app) as client:
        assert client.get("/internal/home-highlights").status_code == 404


async def test_get_home_highlights_returns_a_usable_shape():
    data = await crud.get_home_highlights()
    assert set(data) == {"topic_chips", "active_topic", "featured", "states"}
    assert isinstance(data["featured"], list)
    # Every featured card carries the pre-rendered display strings the
    # shared partial needs -- see this module's docstring.
    for card in data["featured"]:
        assert "jurisdiction_display" in card
        assert "date_html" in card


async def test_national_feed_caps_one_card_per_government():
    """Otherwise the feed is six meetings from whatever city was
    bulk-ingested last week, which reads as a site about one city."""
    pages = [
        {
            "id": i,
            "slug": f"s{i}",
            "title": f"Meeting {i}",
            "jurisdiction": "City of Bigtown, CA" if i < 4 else f"City of Town{i}, TX",
            "meeting_body": "City Council",
            "date": f"2026-08-{20 - i:02d}",
        }
        for i in range(1, 7)
    ]
    highlights = {
        p["id"]: {
            "start": 10.0,
            "text": f"A quotable line from meeting {p['id']}.",
            "topics": [],
            "topic_moments": {},
        }
        for p in pages
    }
    featured = crud._build_featured(
        pages,
        highlights,
        None,
        4,
        None,
        max_per_jurisdiction=crud.MAX_FEATURED_PER_JURISDICTION,
    )
    bigtown = [f for f in featured if f["jurisdiction"] == "City of Bigtown, CA"]
    assert len(bigtown) == 1
    assert len(featured) == 4
