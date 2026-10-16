"""WO-1967: keep the speaker labels a station's captions already carry.

Every caption shape here is a real fixture already in tests/fixtures:

- TelVue, Ashland OR Planning Commission (media 1040134):
  `<v Speaker 1>...</v>` voice tags, sometimes two voices in one cue.
- Orange County FL BCC (generic_fallback): `<v.Male.spk1 Speaker1>`.
- Castus: `<v.Male.spk1.Speaker1>`, classes with no annotation, so no
  speaker name at all.

None of the real fixtures carries a person's name in a voice tag, and none
carries Cablecast's `S1:` or Tampa's "NAME :" inline shape, so those
shapes are not built (see BACKLOG.md). The tests marked synthetic below
reuse the real `<v Name>` tag shape with a real label from the WO-1960
research ("El Cerrito Council Chamber") to exercise the filters.
"""

from fastapi.testclient import TestClient

import archive.main
from app.platforms.telvue import TelvueAssetFinder
from app.utils.vtt_parser import clean_speaker_label, parse_vtt
from archive.db import crud
from archive.utils.transcript_export import to_srt, to_txt

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture
from test_telvue import CAPTIONS_URL, CHAPTERS_URL, PAGE_URL

archive_client = TestClient(archive.main.app)


def test_telvue_voice_tags_become_speakers():
    cues = parse_vtt(load_fixture("telvue", "ashland_planning_1040134_captions.vtt"))
    assert cues[0]["speaker"] == "Speaker 1"
    assert cues[0]["text"] == "Recording in progress."
    # Two voices in one cue: the first one is the cue's speaker.
    assert cues[1]["speaker"] == "Speaker 2"
    assert "<v" not in cues[1]["text"]
    # A cue with no voice tag gets no speaker. We do not carry one forward.
    assert "speaker" not in cues[2]
    labelled = [c["speaker"] for c in cues if "speaker" in c]
    assert labelled[:3] == ["Speaker 1", "Speaker 2", "Speaker 4"]


def test_ocfl_voice_annotation_is_kept_as_written():
    cues = parse_vtt(load_fixture("generic_fallback", "ocfl_bcc071626aa_captions.vtt"))
    assert [c.get("speaker") for c in cues[:3]] == ["Speaker1", "Speaker1", "Speaker2"]
    assert not any("<" in c["text"] for c in cues)


def test_castus_classes_without_annotation_give_no_speaker():
    cues = parse_vtt(load_fixture("castus", "captions.vtt"))
    assert cues
    assert not any("speaker" in c for c in cues)


def test_room_and_device_labels_are_not_speakers():
    # Synthetic: the label is real (a council chamber's video-call account,
    # BACKLOG WO-1960); the tag shape is TelVue's real one.
    assert clean_speaker_label("El Cerrito Council Chamber") is None
    assert clean_speaker_label("  ") is None
    assert clean_speaker_label("Speaker  3") == "Speaker 3"


def test_generic_labels_drop_when_a_file_has_a_name():
    # Synthetic: the real `<v Name>` shape, with one named voice and one
    # generic one. No real fixture has a named voice yet.
    content = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\n<v Speaker 1>Good evening.</v>\n\n"
        "00:00:03.000 --> 00:00:04.000\n<v Mayor Lee>Call to order.</v>\n\n"
        "00:00:05.000 --> 00:00:06.000\n<v El Cerrito Council Chamber>Thank you.</v>\n"
    )
    cues = parse_vtt(content)
    assert "speaker" not in cues[0]
    assert cues[1]["speaker"] == "Mayor Lee"
    assert "speaker" not in cues[2]
    assert cues[2]["text"] == "Thank you."


def test_txt_export_names_the_speaker_where_it_changes():
    segments = [
        {"start": 1.0, "end": 2.0, "text": "a", "speaker": "Speaker 1"},
        {"start": 3.0, "end": 4.0, "text": "b"},
        {"start": 5.0, "end": 6.0, "text": "c", "speaker": "Speaker 1"},
        {"start": 7.0, "end": 8.0, "text": "d", "speaker": "Speaker 2"},
    ]
    assert (
        to_txt(segments)
        == "[0:01] Speaker 1: a\n[0:03] b\n[0:05] c\n[0:07] Speaker 2: d"
    )
    assert "Speaker" not in to_srt(segments)


async def test_meeting_page_shows_speaker_where_it_changes():
    """Real TelVue fixture, resolved, ingested and rendered."""
    routes = {
        PAGE_URL: FakeResponse(
            status=200,
            text=load_fixture("telvue", "ashland_planning_1040134_page.html"),
            url=PAGE_URL,
        ),
        CAPTIONS_URL: FakeResponse(
            status=200,
            text=load_fixture("telvue", "ashland_planning_1040134_captions.vtt"),
            url=CAPTIONS_URL,
        ),
        CHAPTERS_URL: FakeResponse(
            status=200,
            text=load_fixture("telvue", "ashland_planning_1040134_chapters.vtt"),
            url=CHAPTERS_URL,
        ),
    }
    with mock_session(routes):
        result = await TelvueAssetFinder().resolve(PAGE_URL)
    assert result.segments[0].speaker == "Speaker 1"

    payload = result.model_dump()
    payload["external_id"] = "wo1967-speaker-labels"
    stored = await crud.ingest_resolution(payload, PAGE_URL)
    response = archive_client.get(f"/m/{stored['slug']}")
    assert response.status_code == 200
    html = response.text
    assert (
        '<span class="segment-speaker">Speaker 1:</span> Recording in progress.' in html
    )
    # The fixture's 30 cues carry 8 voice tags, each a change from the one
    # before (1, 2, 4, 3, 5, 3, 1, 3). The other 22 lines show no label.
    assert len([s for s in result.segments if s.speaker]) == 8
    assert html.count('class="segment-speaker"') == 8

    txt = archive_client.get(f"/m/{stored['slug']}/transcript.txt").text
    assert txt.splitlines()[0] == "[0:22] Speaker 1: Recording in progress."
