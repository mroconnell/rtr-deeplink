"""Coverage for the agenda_link hedge fix (2026-08-28, see BACKLOG_DONE.md):
"We think we found an agenda here" is only honest for generic_fallback's
actual best-effort scan (platform == "unknown") -- every other adapter
that sets agenda_link (legistar, granicus, champds, hyland, suiteone,
chicago_elms, openmedia, proudcity) pulls a real, confirmed link straight
off the source, so it gets a plain "Agenda:" label instead."""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

JX = "Agendahedgetest City, CA"


def _payload(external_id: str, platform: str) -> dict:
    return {
        "platform": platform,
        "source_url": f"https://example.com/agendahedge/{external_id}",
        "external_id": external_id,
        "title": f"Agendahedge {external_id}",
        "date": "2024-03-05",
        "jurisdiction": JX,
        "video_url": None,
        "video_format": None,
        "segments": [],
        "agenda_items": [],
        "agenda_link": "https://example.com/agendahedge/agenda.pdf",
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _seed(external_id: str, platform: str) -> str:
    payload = _payload(external_id, platform)
    result = await crud.ingest_resolution(payload, payload["source_url"])
    return result["slug"]


async def test_generic_fallback_agenda_link_keeps_the_hedge():
    slug = await _seed("unknown", "unknown")
    response = client.get(f"/m/{slug}")
    assert response.status_code == 200
    assert "We think we found an agenda here" in response.text


async def test_legistar_agenda_link_gets_a_plain_label():
    slug = await _seed("legistar", "legistar")
    response = client.get(f"/m/{slug}")
    assert response.status_code == 200
    assert "We think we found an agenda here" not in response.text
    assert "Agenda:" in response.text
