"""A push's alternate_transcripts (a second caption track the resolver
found, e.g. Spanish next to English) are stored as non-default
TranscriptVersions, and English is the page's default (2026-09-29, Ryan:
"grab both, store them correctly and default to English on the archive
page"). Found on TelVue pages from Tahoe Truckee Media and Fitchburg
Access TV, which list an English and a Spanish track.

Synthetic payloads: the cue text is short real text from TTUSD Trustees,
Sept. 2, 2026 (Spanish track) and the Ashland Planning Commission (English
track) -- see tests/test_telvue.py's two-track fixture. Against the
isolated SQLite fixture DB, same pattern as tests/test_ingest_promotion.py.
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)
_AUTH = {"Authorization": "Bearer test-token"}

EN = [
    {
        "start": 36.8,
        "end": 42.2,
        "text": "I call the regular meeting of the City of Ashland Planning Commission to order",
    }
]
ES = [
    {
        "start": 1.0,
        "end": 3.0,
        "text": "Buenas noches y bienvenidos a la reunión de la Junta del Distrito Escolar",
    }
]


def _payload(url, *, segments, language, alternates=None) -> dict:
    return {
        "platform": "telvue",
        "source_url": url,
        "external_id": "telvue:" + url.rsplit("/", 1)[-1],
        "title": "Test Meeting",
        "date": "2026-09-02",
        "jurisdiction": "City of Test",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments,
        "agenda_items": [],
        "transcript_language": language,
        "transcript_warnings": [],
        "alternate_transcripts": alternates or [],
    }


def _by_language(page):
    return {v["language"]: v for v in page["versions"]}


async def test_alternate_is_stored_as_non_default_version_and_not_duplicated():
    url = "https://videoplayer.telvue.com/player/alt-test/media/1"
    payload = _payload(
        url, segments=EN, language="en", alternates=[{"language": "es", "segments": ES}]
    )
    result = await crud.ingest_resolution(payload, url)
    await crud.ingest_resolution(payload, url)  # a re-check adds nothing

    page = await crud.get_page_by_slug(result["slug"])
    versions = _by_language(page)
    assert len(page["versions"]) == 2
    assert versions["en"]["is_default"] is True
    assert versions["es"]["is_default"] is False


async def test_alternate_survives_the_ingest_route_and_shows_in_the_picker():
    # The field must survive Pydantic at /internal/ingest -- before
    # 2026-09-29 IngestRequest had no such field and dropped it silently.
    url = "https://videoplayer.telvue.com/player/alt-test/media/2"
    body = _payload(
        url, segments=EN, language="en", alternates=[{"language": "es", "segments": ES}]
    )
    body["input_url_normalized"] = url
    response = client.post("/internal/ingest", json=body, headers=_AUTH)
    assert response.status_code == 200
    slug = response.json()["slug"]

    html = client.get(f"/m/{slug}").text
    # Languages are named in their own language in the picker.
    assert "selected>English (sourced)</option>" in html
    assert "Español (sourced)</option>" in html
    assert "City of Ashland Planning Commission" in html  # English is shown
    assert "Buenas noches" not in html  # Spanish waits behind the picker


async def test_alternate_with_unknown_or_same_language_is_skipped():
    url = "https://videoplayer.telvue.com/player/alt-test/media/3"
    other_en = [{"start": 0, "end": 1, "text": "a second English track"}]
    result = await crud.ingest_resolution(
        _payload(
            url,
            segments=EN,
            language="en",
            alternates=[
                {"language": None, "segments": ES},
                {"language": "en", "segments": other_en},
            ],
        ),
        url,
    )
    page = await crud.get_page_by_slug(result["slug"])
    assert [v["language"] for v in page["versions"]] == ["en"]


async def test_english_push_replaces_a_spanish_default_but_never_the_reverse():
    url = "https://videoplayer.telvue.com/player/alt-test/media/4"
    first = await crud.ingest_resolution(_payload(url, segments=ES, language="es"), url)
    await crud.ingest_resolution(_payload(url, segments=EN, language="en"), url)

    page = await crud.get_page_by_slug(first["slug"])
    assert _by_language(page)["en"]["is_default"] is True

    # A later Spanish-only push does not take the default back.
    await crud.ingest_resolution(
        _payload(
            url,
            segments=ES + [{"start": 5, "end": 6, "text": "Gracias."}],
            language="es",
        ),
        url,
    )
    page = await crud.get_page_by_slug(first["slug"])
    default = next(v for v in page["versions"] if v["is_default"])
    assert default["language"] == "en"


async def test_repairing_a_spanish_page_labelled_english():
    # The per-page repair for pages ingested before this fix: the stored
    # default is Spanish text labelled "en". Step 1: correct its label to
    # "es". Step 2: re-ingest with the fixed adapter. English becomes the
    # default and the Spanish version is reused, not copied.
    url = "https://videoplayer.telvue.com/player/alt-test/media/5"
    first = await crud.ingest_resolution(_payload(url, segments=ES, language="en"), url)
    slug = first["slug"]

    await crud.correct_transcript_version_language(slug=slug, language="es")
    await crud.ingest_resolution(
        _payload(
            url,
            segments=EN,
            language="en",
            alternates=[{"language": "es", "segments": ES}],
        ),
        url,
    )

    page = await crud.get_page_by_slug(slug)
    versions = _by_language(page)
    assert len(page["versions"]) == 2
    assert versions["en"]["is_default"] is True
    assert versions["es"]["is_default"] is False
