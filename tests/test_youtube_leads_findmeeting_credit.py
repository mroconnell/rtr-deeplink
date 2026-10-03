"""Find Meeting sources get the 'linked from the government's own site'
credit, unless the address is a template embed shared across states.
Hand-review rows Ryan verified count as identity already confirmed.
No network."""

from scripts import youtube_leads_fetch as f
from scripts.youtube_leads_judge import assess_identity

HEADER = "channel_url,gov_id,government,state,source_wo,kind,verified,note\n"


def _leads(tmp_path, rows):
    p = tmp_path / "leads.csv"
    p.write_text("# comment\n" + HEADER + "".join(rows))
    f._SHARED_ADDRESSES_CACHE.clear()
    return p


def test_findmeeting_source_gets_credit(tmp_path):
    p = _leads(
        tmp_path,
        ["https://www.youtube.com/@cityofx,g1,X,Ohio,findmeeting_a,channel,false,\n"],
    )
    assert f.is_linked_from_gov_site(
        "findmeeting_big_job_govs_01", "https://www.youtube.com/@cityofx", p
    )
    assert f.is_linked_from_gov_site(
        "findmeeting_catchup_youtube_2026-10-03", "https://www.youtube.com/@cityofx", p
    )


def test_same_address_in_different_states_gets_no_credit(tmp_path):
    p = _leads(
        tmp_path,
        [
            "https://www.youtube.com/embed/bqLUp7GuUTg,g1,A,Ohio,findmeeting_a,single_video,false,\n",
            "https://www.youtube.com/watch?v=bqLUp7GuUTg,g2,B,Texas,findmeeting_b,single_video,false,\n",
            "https://www.youtube.com/@dewi11Channel,g3,C,Ohio,findmeeting_a,channel,false,\n",
            "https://www.youtube.com/@DEWI11channel,g4,D,Iowa,WO-353,channel,false,\n",
        ],
    )
    assert not f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/embed/bqLUp7GuUTg", p
    )
    assert not f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/@dewi11Channel", p
    )


def test_same_address_in_same_state_keeps_credit(tmp_path):
    p = _leads(
        tmp_path,
        [
            "https://www.youtube.com/@county,g1,A town,Ohio,findmeeting_a,channel,false,\n",
            "https://www.youtube.com/@county,g2,B town,Ohio,findmeeting_a,channel,false,\n",
        ],
    )
    assert f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/@county", p
    )


def test_unreadable_leads_file_gives_no_findmeeting_credit(tmp_path):
    f._SHARED_ADDRESSES_CACHE.clear()
    assert not f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/@x", tmp_path / "missing.csv"
    )


def test_existing_wo_sources_unchanged(tmp_path):
    p = tmp_path / "missing.csv"
    assert f.is_linked_from_gov_site("WO-353", "https://www.youtube.com/@x", p, [])
    assert not f.is_linked_from_gov_site(
        "meeting-finder-2026-09-24-run3", "https://www.youtube.com/@x", p
    )
    assert not f.is_linked_from_gov_site("WO-1131", "https://www.youtube.com/@x", p, [])
    assert not f.is_linked_from_gov_site("", "https://www.youtube.com/@x", p, [])


def test_hand_review_verified_is_person_confirmed():
    assert f.is_person_confirmed(
        {"source_wo": "hand_review_2026-10-03", "verified": "true"}
    )
    assert f.is_person_confirmed({"source_wo": "hand_review_x", "verified": "True"})
    assert not f.is_person_confirmed(
        {"source_wo": "hand_review_x", "verified": "false"}
    )
    assert not f.is_person_confirmed({"source_wo": "findmeeting_x", "verified": "true"})
    assert not f.is_person_confirmed({"source_wo": "WO-353", "verified": "true"})


def test_person_confirmed_is_strong_even_without_a_name_match():
    kw = dict(
        channel_title="Brockport Meetings",
        channel_description="",
        gov_name="Village of Somewhere Else",
        gov_state="NY",
        gov_kind="municipality",
        linked_from_gov_site=False,
        kind="channel",
    )
    assert assess_identity(**kw).tier == "needs-human"
    assert assess_identity(confirmed_by_person=True, **kw).tier == "strong"


def test_name_match_alone_stays_medium_for_unlisted_source():
    v = assess_identity(
        channel_title="City of Springfield",
        channel_description="",
        gov_name="Springfield city",
        gov_state="IL",
        gov_kind="municipality",
        linked_from_gov_site=False,
        kind="channel",
    )
    assert v.tier == "medium"


def test_state_abbreviation_and_full_name_are_the_same_state(tmp_path):
    p = _leads(
        tmp_path,
        [
            "https://www.youtube.com/@twice,g1,A,SC,findmeeting_a,channel,false,\n",
            "https://www.youtube.com/@twice,g1,A,South Carolina,findmeeting_a,channel,false,\n",
        ],
    )
    assert f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/@twice", p, []
    )


def test_addresses_seen_in_a_handoff_file_count_across_states(tmp_path):
    p = _leads(
        tmp_path,
        ["https://www.youtube.com/@own,g1,A,Ohio,findmeeting_a,channel,false,\n"],
    )
    h = tmp_path / "handoff.csv"
    h.write_text(
        "gov_id,government,state,lane,lead_url,kind,all_youtube_addresses_seen\n"
        "g2,B,Texas,youtube,https://www.youtube.com/@x1,channel,https://www.youtube.com/embed/AAAAAAAAAAA?rel=0 https://www.youtube.com/@own\n"
    )
    f._SHARED_ADDRESSES_CACHE.clear()
    assert not f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/@own", p, [h]
    )
    assert f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/@own", p, []
    )


def test_named_template_embeds_never_get_credit(tmp_path):
    p = _leads(
        tmp_path,
        [
            "https://www.youtube.com/@dewi11Channel,g1,A,Ohio,findmeeting_a,channel,false,\n"
        ],
    )
    assert not f.is_linked_from_gov_site(
        "findmeeting_a", "https://youtube.com/@dewi11Channel", p, []
    )
    assert not f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/embed/bqLUp7GuUTg?rel=0", p, []
    )
