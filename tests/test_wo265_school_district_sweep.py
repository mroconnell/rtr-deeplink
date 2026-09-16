"""WO-265 (2026-09-11): regression coverage for the pure parsing/label/
rate-limit helpers in `scripts/wo265_school_district_sweep.py`, the
overnight detection-only school-district sweep. This sweep is detection
only (no ingest/queue/pin/research-file write), so there is no live
ingest path to fixture-verify the way an adapter's `resolve()` would be
-- these tests cover the logic this script's OWN report depends on being
correct: link/URL-shape scanning, label guessing, and the BoardDocs/
Simbli single-host rate-limit rule. The HTML fixtures below are
hand-built (synthetic), per CLAUDE.md's synthetic-test convention: they
reuse a schema already confirmed real elsewhere in this repo (the same
anchor/iframe tag shapes `wo147_access_ladder_sweep.py`'s own real-page
scans already handle) rather than inventing a new one, and each real-world
fact referenced (a real BoardDocs/CivicClerk/Granicus/IQM2/eScribe URL
shape, a real YouTube/Vimeo channel vs. single-video URL shape) is the
same shape already confirmed live elsewhere in this repo's platform
adapters -- not a fabricated guess.
"""

from scripts.wo265_school_district_sweep import (
    RateLimiter,
    base_label,
    candidate_domains,
    find_boarddocs_or_simbli_link,
    find_channel_leads,
    find_platform_link,
    find_school_hop_links,
    find_video_candidates,
    host_alias,
    is_challenge,
    is_confirmed_dead,
    label_variants,
    looks_like_real_tenant,
    state_abbr_for,
)


def test_find_platform_link_recognizes_civicclerk_anchor():
    html = (
        "<html><body><a href='https://example.portal.civicclerk.com/'>"
        "Meetings</a></body></html>"
    )
    hit = find_platform_link(html, "https://exampleisd.org/")
    assert hit is not None
    assert hit[0] == "civicclerk"


def test_find_platform_link_ignores_vendor_marketing_apex():
    # A bare "Powered by Granicus" footer badge linking the vendor's own
    # marketing homepage is not a real per-tenant instance -- same false
    # positive `wo147_access_ladder_sweep.py`'s own comments describe.
    html = "<html><body><a href='https://www.granicus.com/'>Powered by Granicus</a></body></html>"
    assert find_platform_link(html, "https://exampleisd.org/") is None


def test_find_platform_link_skips_bare_youtube_channel_link():
    # Real bug caught in this script's own smoke test (2026-09-11):
    # Albertville City School District, AL and Hoover City School
    # District, AL both front-page straight to a bare
    # `youtube.com/@handle` link with no /watch, playlist, or /embed/
    # marker -- that is a CHANNEL lead, not a specific meeting/video, and
    # must fall through to `find_channel_leads()` rather than being
    # claimed here as `platform-found`.
    html = "<html><body><a href='https://www.youtube.com/@ExampleISD'>Our Channel</a></body></html>"
    assert find_platform_link(html, "https://exampleisd.org/") is None


def test_find_platform_link_accepts_specific_youtube_watch_link():
    html = "<html><body><a href='https://www.youtube.com/watch?v=abc123XYZ'>Last Meeting</a></body></html>"
    hit = find_platform_link(html, "https://exampleisd.org/")
    assert hit is not None
    assert hit[0] == "youtube"


def test_find_boarddocs_link():
    html = "<html><body><a href='https://go.boarddocs.com/az/exampleusd/Board.nsf/Public'>Board Docs</a></body></html>"
    hit = find_boarddocs_or_simbli_link(html, "https://exampleisd.org/")
    assert hit == (
        "boarddocs",
        "https://go.boarddocs.com/az/exampleusd/Board.nsf/Public",
    )


def test_find_boarddocs_or_simbli_link_finds_simbli():
    html = "<html><body><a href='https://simbli.eboardsolutions.com/SB_Meetings/SB_MeetingListing.aspx?S=1234'>Board Meetings</a></body></html>"
    hit = find_boarddocs_or_simbli_link(html, "https://exampleisd.org/")
    assert hit is not None
    assert hit[0] == "simbli"


def test_find_boarddocs_or_simbli_link_none_when_absent():
    html = "<html><body><a href='/about'>About</a></body></html>"
    assert find_boarddocs_or_simbli_link(html, "https://exampleisd.org/") is None


def test_find_school_hop_links_matches_board_of_education():
    html = (
        "<html><body>"
        "<a href='/trash-schedule'>Trash Pickup</a>"
        "<a href='/board-of-education'>Board of Education</a>"
        "</body></html>"
    )
    links = find_school_hop_links(html, "https://exampleisd.org/")
    assert links == ["https://exampleisd.org/board-of-education"]


def test_find_school_hop_links_matches_agendas_and_minutes():
    html = (
        "<html><body><a href='/agendas-minutes'>Agendas &amp; Minutes</a></body></html>"
    )
    links = find_school_hop_links(html, "https://exampleisd.org/")
    assert links == ["https://exampleisd.org/agendas-minutes"]


def test_find_video_candidates_youtube_and_vimeo():
    html = (
        "<html><body>"
        "<a href='https://www.youtube.com/watch?v=abc123XYZ'>Watch</a>"
        "<a href='https://vimeo.com/123456789'>Watch on Vimeo</a>"
        "<a href='/agenda.pdf'>Agenda</a>"
        "</body></html>"
    )
    vids = find_video_candidates(html, "https://exampleisd.org/board")
    kinds = {k for k, _ in vids}
    assert "youtube" in kinds
    assert "vimeo" in kinds
    assert len(vids) == 2


def test_find_video_candidates_direct_file_and_boxcast():
    html = (
        "<html><body>"
        "<source src='https://cdn.exampleisd.org/meetings/2026-09-10.mp4'>"
        "<a href='https://exampleisd.boxcast.tv/'>Live</a>"
        "</body></html>"
    )
    vids = find_video_candidates(html, "https://exampleisd.org/board")
    kinds = {k for k, _ in vids}
    assert "direct_file" in kinds
    assert "boxcast" in kinds


def test_find_channel_leads_distinguishes_channel_from_single_video():
    html = (
        "<html><body>"
        "<a href='https://www.youtube.com/@ExampleISDBoard'>Our Channel</a>"
        "<a href='https://www.youtube.com/watch?v=abc123XYZ'>One Meeting</a>"
        "</body></html>"
    )
    chans = find_channel_leads(html, "https://exampleisd.org/board")
    assert chans == ["https://www.youtube.com/@ExampleISDBoard"]


def test_looks_like_real_tenant_rejects_short_or_error_pages():
    assert looks_like_real_tenant(None) is False
    assert looks_like_real_tenant("<html><body>hi</body></html>") is False
    long_error = "<html><body>" + ("Page Not Found. " * 40) + "</body></html>"
    assert looks_like_real_tenant(long_error) is False


def test_looks_like_real_tenant_accepts_a_real_looking_page():
    long_ok = (
        "<html><body>"
        + ("Board of Education meeting agenda item. " * 30)
        + "</body></html>"
    )
    assert looks_like_real_tenant(long_ok) is True


def test_base_label_strips_common_district_suffixes():
    assert base_label("albertk12.org") == "albert"
    assert base_label("exampleisd.org") == "example"
    assert base_label("www.examplecusd.k12.ca.us") == "example"


def test_label_variants_includes_common_forms():
    variants = label_variants("example.org")
    assert variants[0] == "example"
    assert "exampleisd" in variants
    assert "exampleschools" in variants
    assert len(variants) == len(set(variants))


def test_candidate_domains_includes_primary_and_alternates():
    row = {
        "domain": "exampleisd.org",
        "alternate_domains": "example-schools.net;exampleisd.org",
        "alternate_urls": "https://old.exampleisd.org/home",
    }
    domains = candidate_domains(row)
    assert domains[0] == "exampleisd.org"
    assert "example-schools.net" in domains
    assert "old.exampleisd.org" in domains
    # the duplicate in alternate_domains is not repeated
    assert domains.count("exampleisd.org") == 1


def test_host_alias_groups_boarddocs_and_simbli_as_one_host_each():
    assert host_alias("go.boarddocs.com") == "go.boarddocs.com"
    assert host_alias("www.boarddocs.com") == "go.boarddocs.com"
    assert host_alias("simbli.eboardsolutions.com") == "simbli.eboardsolutions.com"
    assert host_alias("otherstate.eboardsolutions.com") == "simbli.eboardsolutions.com"
    assert host_alias("exampleisd.org") == "exampleisd.org"


def test_is_confirmed_dead_matches_named_handover_entries():
    # Real, named findings from SCHOOL_DISTRICT_ENUMERATION_HANDOVER.md
    # (a read-only sibling repo -- see this script's own SKIP_LIST comment).
    assert is_confirmed_dead("Putnam School District", "Connecticut") is True
    assert is_confirmed_dead("Corpus Christi ISD", "Texas") is True
    assert is_confirmed_dead("Hernando County School District", "Florida") is True


def test_is_confirmed_dead_false_for_unrelated_district():
    assert is_confirmed_dead("Albertville City School District", "Alabama") is False


def test_is_confirmed_dead_requires_matching_state_not_just_name():
    # "Putnam" also exists outside Connecticut -- must not skip those.
    assert is_confirmed_dead("Putnam County School District", "New York") is False


def test_state_abbr_for_full_name_and_passthrough():
    assert state_abbr_for("Alabama") == "AL"
    assert state_abbr_for("AZ") == "AZ"
    assert state_abbr_for("") == ""
    assert state_abbr_for("Not A Real State") == ""


def test_is_challenge_detects_cloudflare_marker():
    assert is_challenge("<title>Just a moment...</title>") is True
    assert (
        is_challenge("<html><body>Welcome to our school district</body></html>")
        is False
    )


def test_rate_limiter_cooloff_after_six_consecutive_failures():
    rl = RateLimiter()
    for _ in range(6):
        rl.record("go.boarddocs.com", access_ok=False)
    assert rl.consecutive_failures["go.boarddocs.com"] == 6
    rl.record("go.boarddocs.com", access_ok=True)
    assert rl.consecutive_failures["go.boarddocs.com"] == 0


def test_rate_limiter_treats_boarddocs_subdomains_as_one_bucket():
    rl = RateLimiter()
    rl.record("go.boarddocs.com", access_ok=False)
    rl.record("www.boarddocs.com", access_ok=False)
    assert rl.consecutive_failures["go.boarddocs.com"] == 2
