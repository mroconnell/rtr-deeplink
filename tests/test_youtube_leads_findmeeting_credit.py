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
        "findmeeting_a", "https://www.youtube.com/@x", tmp_path / "missing.csv", []
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


# --- research file missing (the drip Mac): handoff leads.csv files alone ---

HANDOFF_HEADER = (
    "gov_id,government,state,lane,lead_url,kind,meeting_source_has_no_video,"
    "run,all_youtube_addresses_seen\n"
)


def _handoff(tmp_path, rows, name="handoff.csv"):
    h = tmp_path / name
    h.write_text(HANDOFF_HEADER + "".join(rows))
    f._SHARED_ADDRESSES_CACHE.clear()
    return h


def test_missing_research_file_uses_handoff_files_alone(tmp_path, caplog):
    h = _handoff(
        tmp_path,
        [
            "g1,A,Ohio,youtube,https://www.youtube.com/@own,channel,no,run_govs_01,\n",
            "g2,B,Ohio,youtube,https://www.youtube.com/@same,channel,no,run_govs_01,\n",
            "g3,C,Ohio,youtube,https://www.youtube.com/@same,channel,no,run_govs_01,\n",
            "g4,D,Texas,youtube,https://www.youtube.com/@cross,channel,no,run_govs_01,\n",
            "g5,E,Iowa,youtube,https://www.youtube.com/@cross,channel,no,run_govs_01,\n",
        ],
    )
    missing = tmp_path / "nope.csv"
    with caplog.at_level("INFO", logger=f.logger.name):
        # no research file, so same-state and unseen addresses are credited
        assert f.is_linked_from_gov_site(
            "findmeeting_a", "https://www.youtube.com/@same", missing, [h]
        )
        # cross-state address is refused
        assert not f.is_linked_from_gov_site(
            "findmeeting_a", "https://www.youtube.com/@cross", missing, [h]
        )
        # template address is refused
        assert not f.is_linked_from_gov_site(
            "findmeeting_a", "https://www.youtube.com/@dewi11Channel", missing, [h]
        )
    lines = [
        r.getMessage() for r in caplog.records if "leads guard source" in r.getMessage()
    ]
    assert len(lines) == 1
    assert "handoff leads.csv only" in lines[0]


def test_research_file_present_is_named_in_the_log(tmp_path, caplog):
    p = _leads(
        tmp_path,
        ["https://www.youtube.com/@a,g1,A,Ohio,findmeeting_a,channel,false,\n"],
    )
    with caplog.at_level("INFO", logger=f.logger.name):
        f.is_linked_from_gov_site("findmeeting_a", "https://www.youtube.com/@a", p, [])
    assert any("research leads file" in r.getMessage() for r in caplog.records)


def test_nothing_readable_gives_no_credit_even_for_handoff_run(tmp_path):
    f._SHARED_ADDRESSES_CACHE.clear()
    missing = tmp_path / "nope.csv"
    assert not f.is_linked_from_gov_site(
        "run_govs_01", "https://www.youtube.com/@x", missing, [tmp_path / "gone.csv"]
    )
    assert not f.is_linked_from_gov_site(
        "", "https://www.youtube.com/@x", missing, [tmp_path / "gone.csv"]
    )


def test_handoff_run_prefixes_get_credit_as_source(tmp_path):
    h = _handoff(
        tmp_path,
        ["g1,A,Ohio,youtube,https://www.youtube.com/@own,channel,no,run_govs_01,\n"],
    )
    missing = tmp_path / "nope.csv"
    u = "https://www.youtube.com/@own"
    for src in ("run_govs_02", "group4_final_run", "findmeeting_low_x"):
        assert f.is_linked_from_gov_site(src, u, missing, [h])
    # hand_review is Ryan's own decision path, not this credit
    assert not f.is_linked_from_gov_site("hand_review_2026-10-03", u, missing, [h])
    assert not f.is_linked_from_gov_site("WO-1131", u, missing, [h])


def test_blank_source_is_looked_up_by_handoff_run(tmp_path):
    h = _handoff(
        tmp_path,
        [
            "g1,A,Ohio,youtube,https://www.youtube.com/@own,channel,no,group4_final_run,\n",
            "g2,B,Ohio,vimeo,https://vimeo.com/user1,channel,yes,hand_review_2026-10-03,\n",
            "g3,C,Texas,youtube,https://www.youtube.com/@x,channel,no,run_govs_01,\n",
            "g4,D,Iowa,youtube,https://www.youtube.com/@x,channel,no,run_govs_01,\n",
        ],
    )
    missing = tmp_path / "nope.csv"
    assert f.is_linked_from_gov_site("", "https://www.youtube.com/@own", missing, [h])
    # unknown address: no run known, no credit
    assert not f.is_linked_from_gov_site(
        "", "https://www.youtube.com/@zzz", missing, [h]
    )
    # hand-review run: no credit through this path
    assert not f.is_linked_from_gov_site("", "https://vimeo.com/user1", missing, [h])
    # cross-state still refused
    assert not f.is_linked_from_gov_site("", "https://www.youtube.com/@x", missing, [h])


def test_env_var_sets_leads_path(tmp_path, monkeypatch):
    p = _leads(
        tmp_path,
        [
            "https://www.youtube.com/@cross,g1,A,Ohio,findmeeting_a,channel,false,\n",
            "https://www.youtube.com/@cross,g2,B,Texas,findmeeting_a,channel,false,\n",
        ],
    )
    monkeypatch.setenv("RTR_LEADS_CSV", str(p))
    assert f.leads_csv_path() == p
    f._SHARED_ADDRESSES_CACHE.clear()
    assert not f.is_linked_from_gov_site(
        "findmeeting_a", "https://www.youtube.com/@cross", None, []
    )
    monkeypatch.delenv("RTR_LEADS_CSV")
    assert f.leads_csv_path() == f.DEFAULT_LEADS_CSV


def test_low_confidence_findmeeting_gets_no_credit(tmp_path):
    h = _handoff(
        tmp_path,
        [
            "g1,A,Ohio,youtube,https://www.youtube.com/@low,channel,,findmeeting_low_confidence_2026-10-03,\n",
            "g2,B,Ohio,youtube,https://www.youtube.com/@ok,channel,,findmeeting_conflict_accepted_2026-10-03,\n",
        ],
    )
    missing = tmp_path / "nope.csv"
    low = "https://www.youtube.com/@low"
    assert not f.is_linked_from_gov_site(
        "findmeeting_low_confidence_2026-10-03", low, missing, [h]
    )
    assert not f.is_linked_from_gov_site("", low, missing, [h])
    ok = "https://www.youtube.com/@ok"
    assert f.is_linked_from_gov_site(
        "findmeeting_conflict_accepted_2026-10-03", ok, missing, [h]
    )
    assert f.is_linked_from_gov_site("", ok, missing, [h])
