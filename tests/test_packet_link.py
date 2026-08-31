"""Coverage for `packet_link` end to end (2026-08-31): ingest -> stored on
MeetingPage -> rendered on /m/{slug} as a plain outbound link, separate
from `agenda_link`'s inline iframe. See archive/db/models.py's
MeetingPage.packet_link comment for why it's never folded into
agenda_link (a packet can run to tens of megabytes)."""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

JX = "Packetlinktest City, CA"


def _payload(external_id: str, **overrides) -> dict:
    payload = {
        "platform": "civicclerk",
        "source_url": f"https://example.com/packetlink/{external_id}",
        "external_id": external_id,
        "title": f"Packet link test {external_id}",
        "date": "2024-03-05",
        "jurisdiction": JX,
        "video_url": None,
        "video_format": None,
        "segments": [],
        "agenda_items": [],
        "agenda_link": "https://example.com/packetlink/agenda.pdf",
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


async def _seed(external_id: str, **overrides) -> str:
    payload = _payload(external_id, **overrides)
    result = await crud.ingest_resolution(payload, payload["source_url"])
    return result["slug"]


async def test_packet_link_renders_as_a_plain_outbound_link():
    slug = await _seed(
        "with-packet", packet_link="https://example.com/packetlink/packet.pdf"
    )
    response = client.get(f"/m/{slug}")
    assert response.status_code == 200
    assert "Full agenda packet" in response.text
    assert "https://example.com/packetlink/packet.pdf" in response.text
    # A plain <a> link, not a second iframe -- packets can run to tens of
    # megabytes, so it must never get the inline-viewer treatment
    # agenda_link gets.
    assert response.text.count("agenda-inline-frame") == 1


async def test_no_packet_link_renders_nothing_extra():
    slug = await _seed("no-packet")
    response = client.get(f"/m/{slug}")
    assert response.status_code == 200
    assert "Full agenda packet" not in response.text


async def test_packet_link_identical_to_agenda_link_is_not_shown_twice():
    # A platform could plausibly set both to the same URL -- showing two
    # identical links would just be confusing, not additive information.
    same_url = "https://example.com/packetlink/agenda.pdf"
    slug = await _seed("same-as-agenda", agenda_link=same_url, packet_link=same_url)
    response = client.get(f"/m/{slug}")
    assert response.status_code == 200
    assert "Full agenda packet" not in response.text


async def test_packet_link_survives_ingest_and_is_queryable():
    slug = await _seed(
        "queryable", packet_link="https://example.com/packetlink/packet2.pdf"
    )
    page = await crud.get_page_by_slug(slug)
    assert page is not None
    assert page["packet_link"] == "https://example.com/packetlink/packet2.pdf"
