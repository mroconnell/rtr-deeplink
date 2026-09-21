"""Pure unit tests for archive/utils/context_links.py -- no DB, no network,
same as the module itself. URL shapes here are either real, verifiable
links (the three Instagram ones named below, from CLAUDE.md's "test
against real data" convention) or synthetic-but-realistic shapes built
against a schema already confirmed live (real TikTok/YouTube video-id
lengths and characters, real platform host names) -- marked as such where
it matters, per CLAUDE.md's "Synthetic tests" section.
"""

import pytest

from archive.utils.context_links import (
    CONTEXT_SUMMARY_MAX,
    ContextLinkError,
    embed_for,
    parse_rtr_link,
    parse_social_url,
)

# --- parse_social_url: real, confirmed URLs -------------------------------
# Real, live Instagram posts (named in this WO's own brief) -- not
# fabricated shapes.
REAL_INSTAGRAM_POST = "https://www.instagram.com/p/DdF8tEDMtZs/"
REAL_INSTAGRAM_POST_WITH_TRACKING = (
    "https://www.instagram.com/p/DdWy-SCmtUi/?igsh=abc123"
)
REAL_INSTAGRAM_REEL = "https://www.instagram.com/reel/Db7MIbVu2kO/"


def test_real_instagram_post_parses():
    ref = parse_social_url(REAL_INSTAGRAM_POST)
    assert ref.network == "instagram"
    assert ref.canonical_url == "https://www.instagram.com/p/DdF8tEDMtZs/"
    assert ref.key == "instagram:DdF8tEDMtZs"


def test_real_instagram_post_strips_tracking_param():
    ref = parse_social_url(REAL_INSTAGRAM_POST_WITH_TRACKING)
    assert ref.canonical_url == "https://www.instagram.com/p/DdWy-SCmtUi/"
    assert "igsh" not in ref.canonical_url
    assert ref.key == "instagram:DdWy-SCmtUi"


def test_real_instagram_reel_parses():
    ref = parse_social_url(REAL_INSTAGRAM_REEL)
    assert ref.network == "instagram"
    assert ref.key == "instagram:Db7MIbVu2kO"


def test_instagram_post_and_reel_of_same_code_share_a_key():
    # Synthetic pairing (not the same real post), built only to confirm
    # the /p/ vs /reel/ dedupe rule the brief calls out explicitly.
    post = parse_social_url("https://www.instagram.com/p/AbCdEfGhIjK/")
    reel = parse_social_url("https://www.instagram.com/reel/AbCdEfGhIjK/")
    assert post.key == reel.key == "instagram:AbCdEfGhIjK"


def test_instagram_post_with_leading_username_segment():
    ref = parse_social_url("https://www.instagram.com/cityhallwatch/p/DdF8tEDMtZs/")
    assert ref.key == "instagram:DdF8tEDMtZs"
    assert ref.canonical_url == REAL_INSTAGRAM_POST


def test_instagram_profile_link_is_link_out_only():
    ref = parse_social_url("https://www.instagram.com/cityhallwatch/")
    assert ref.network == "instagram"
    assert ref.key.startswith("url:")


# --- parse_social_url: TikTok (synthetic, real id shape) ------------------


def test_tiktok_video_url_parses():
    # Synthetic account/id -- real TikTok video ids are this many digits,
    # but this specific id is not a claim about a real post.
    ref = parse_social_url("https://www.tiktok.com/@cityhall/video/7123456789012345678")
    assert ref.network == "tiktok"
    assert ref.key == "tiktok:7123456789012345678"
    assert ref.canonical_url == (
        "https://www.tiktok.com/@cityhall/video/7123456789012345678"
    )


def test_tiktok_short_link_is_link_out_only():
    ref = parse_social_url("https://vm.tiktok.com/ZMabcdefg/")
    assert ref.network == "tiktok"
    assert ref.key.startswith("url:")


def test_tiktok_slash_t_short_link_is_link_out_only():
    ref = parse_social_url("https://www.tiktok.com/t/ZTabcdefg/")
    assert ref.network == "tiktok"
    assert ref.key.startswith("url:")


# --- parse_social_url: YouTube ---------------------------------------------


def test_youtube_watch_url_parses():
    ref = parse_social_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert ref.network == "youtube"
    assert ref.key == "youtube:dQw4w9WgXcQ"
    assert ref.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_youtube_short_link_resolves_to_same_key_as_watch_url():
    ref = parse_social_url("https://youtu.be/dQw4w9WgXcQ")
    assert ref.key == "youtube:dQw4w9WgXcQ"
    assert ref.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_youtube_shorts_url_keeps_shorts_shape():
    ref = parse_social_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert ref.key == "youtube:dQw4w9WgXcQ"
    assert ref.canonical_url == "https://www.youtube.com/shorts/dQw4w9WgXcQ"


def test_youtube_channel_url_has_no_video_id_and_is_link_out_only():
    ref = parse_social_url("https://www.youtube.com/@somechannel")
    assert ref.network == "youtube"
    assert ref.key.startswith("url:")


# --- parse_social_url: label-only networks --------------------------------


@pytest.mark.parametrize(
    "url,expected_network",
    [
        ("https://www.facebook.com/watch/?v=12345", "facebook"),
        ("https://fb.watch/abc123/", "facebook"),
        ("https://x.com/someuser/status/12345", "x"),
        ("https://twitter.com/someuser/status/12345", "x"),
        ("https://www.threads.net/@someuser/post/abc123", "threads"),
        ("https://bsky.app/profile/someuser.bsky.social/post/abc123", "bluesky"),
        ("https://www.reddit.com/r/somesub/comments/abc123/title/", "reddit"),
        ("https://old.reddit.com/r/somesub/comments/abc123/title/", "reddit"),
        ("https://www.linkedin.com/posts/someuser_abc123", "linkedin"),
        ("https://some-random-news-outlet.example.com/story/123", "other"),
    ],
)
def test_label_only_networks_recognized(url, expected_network):
    ref = parse_social_url(url)
    assert ref.network == expected_network
    assert ref.key.startswith("url:")


def test_tracking_params_stripped_but_meaningful_params_kept():
    ref = parse_social_url(
        "https://www.reddit.com/r/somesub/comments/abc123/title/"
        "?utm_source=share&utm_medium=web&t=5&keep=me"
    )
    assert "utm_source" not in ref.canonical_url
    assert "utm_medium" not in ref.canonical_url
    # "t" is deliberately NOT stripped -- it can carry real meaning on a
    # generic URL, unlike an actual tracking param.
    assert "t=5" in ref.canonical_url
    assert "keep=me" in ref.canonical_url


# --- parse_social_url: rejections ------------------------------------------


@pytest.mark.parametrize(
    "url,expected_code",
    [
        ("http://example.com/x", "insecure_url"),
        ("ftp://example.com/x", "insecure_url"),
        ("https://user:pass@example.com/x", "invalid_url"),
        ("https://example.com:8443/x", "invalid_url"),
        ("https://192.168.1.1/x", "invalid_url"),
        ("https://[::1]/x", "invalid_url"),
        ("https://localhost/x", "invalid_url"),
        ("https://no-dot-host/x", "invalid_url"),
        ("not a url at all", "insecure_url"),
        ("", "invalid_url"),
        ("   ", "invalid_url"),
    ],
)
def test_parse_social_url_rejections(url, expected_code):
    with pytest.raises(ContextLinkError) as exc_info:
        parse_social_url(url)
    assert exc_info.value.code == expected_code
    # The message is what an editor actually sees -- must be non-empty,
    # plain text, not just an internal code.
    assert exc_info.value.message


def test_parse_social_url_rejects_overlong_url():
    huge = "https://example.com/" + ("a" * 3000)
    with pytest.raises(ContextLinkError) as exc_info:
        parse_social_url(huge)
    assert exc_info.value.code == "url_too_long"


def test_generic_url_key_too_long_raises():
    # A link-out-only URL whose normalized form alone exceeds the 512-char
    # key budget -- long enough to blow the key, short enough to stay
    # under the raw 2048-char url_too_long cap tested above, so this
    # exercises the second, independent length check.
    huge_but_not_2048 = "https://example.com/" + ("a" * 600)
    with pytest.raises(ContextLinkError) as exc_info:
        parse_social_url(huge_but_not_2048)
    assert exc_info.value.code == "url_too_long"


# --- embed_for --------------------------------------------------------


def test_embed_for_youtube():
    embed = embed_for("youtube", "https://youtu.be/dQw4w9WgXcQ")
    assert embed == {"kind": "youtube", "video_id": "dQw4w9WgXcQ"}


def test_embed_for_instagram():
    embed = embed_for("instagram", REAL_INSTAGRAM_REEL)
    assert embed == {"kind": "instagram", "permalink": REAL_INSTAGRAM_REEL}


def test_embed_for_tiktok():
    embed = embed_for(
        "tiktok", "https://www.tiktok.com/@cityhall/video/7123456789012345678"
    )
    assert embed == {
        "kind": "tiktok",
        "video_id": "7123456789012345678",
        "cite": "https://www.tiktok.com/@cityhall/video/7123456789012345678",
    }


def test_embed_for_facebook_is_none():
    assert embed_for("facebook", "https://www.facebook.com/watch/?v=12345") is None


def test_embed_for_never_raises_on_garbage():
    assert embed_for("youtube", "not a url") is None
    assert embed_for("youtube", "") is None
    assert embed_for("instagram", "https://evil.com/whatever") is None


def test_embed_for_mismatched_stored_network_returns_none():
    # The stored network disagrees with what a fresh re-parse produces --
    # degrade to no embed rather than show the wrong player.
    assert embed_for("tiktok", "https://youtu.be/dQw4w9WgXcQ") is None


# --- parse_rtr_link ---------------------------------------------------

BASE = "https://redtaperecordings.com"
REAL_SLUG = "some-city-ca-2026-01-01-city-council-regular-meeting"


def test_parse_rtr_link_full_prod_url_with_t_line_version():
    slug, t = parse_rtr_link(f"{BASE}/m/{REAL_SLUG}?t=123&line=5&version=2", BASE)
    assert slug == REAL_SLUG
    assert t == 123


def test_parse_rtr_link_relative_path():
    slug, t = parse_rtr_link(f"/m/{REAL_SLUG}?t=45", BASE)
    assert slug == REAL_SLUG
    assert t == 45


def test_parse_rtr_link_relative_path_no_timestamp():
    slug, t = parse_rtr_link(f"/m/{REAL_SLUG}", BASE)
    assert slug == REAL_SLUG
    assert t is None


def test_parse_rtr_link_bare_slug():
    slug, t = parse_rtr_link(REAL_SLUG, BASE)
    assert slug == REAL_SLUG
    assert t is None


def test_parse_rtr_link_localhost_with_port_http_allowed():
    slug, t = parse_rtr_link(f"http://localhost:8010/m/{REAL_SLUG}?t=5", BASE)
    assert slug == REAL_SLUG
    assert t == 5


def test_parse_rtr_link_127_0_0_1_with_port():
    slug, t = parse_rtr_link(f"http://127.0.0.1:8010/m/{REAL_SLUG}", BASE)
    assert slug == REAL_SLUG


def test_parse_rtr_link_www_prod_host():
    slug, t = parse_rtr_link(f"https://www.redtaperecordings.com/m/{REAL_SLUG}", BASE)
    assert slug == REAL_SLUG


def test_parse_rtr_link_matches_configured_public_base_url():
    slug, t = parse_rtr_link(
        f"https://staging.example.com/m/{REAL_SLUG}?t=9", "https://staging.example.com"
    )
    assert slug == REAL_SLUG
    assert t == 9


def test_parse_rtr_link_foreign_host_rejected():
    with pytest.raises(ContextLinkError) as exc_info:
        parse_rtr_link(f"https://evil.com/m/{REAL_SLUG}", BASE)
    assert exc_info.value.code == "not_rtr_link"


def test_parse_rtr_link_negative_timestamp_rejected():
    with pytest.raises(ContextLinkError) as exc_info:
        parse_rtr_link(f"{BASE}/m/{REAL_SLUG}?t=-5", BASE)
    assert exc_info.value.code == "invalid_timestamp"


def test_parse_rtr_link_huge_timestamp_rejected():
    with pytest.raises(ContextLinkError) as exc_info:
        parse_rtr_link(f"{BASE}/m/{REAL_SLUG}?t=999999999", BASE)
    assert exc_info.value.code == "invalid_timestamp"


def test_parse_rtr_link_non_numeric_timestamp_rejected():
    with pytest.raises(ContextLinkError) as exc_info:
        parse_rtr_link(f"{BASE}/m/{REAL_SLUG}?t=abc", BASE)
    assert exc_info.value.code == "invalid_timestamp"


def test_parse_rtr_link_extra_path_suffix_rejected():
    with pytest.raises(ContextLinkError) as exc_info:
        parse_rtr_link(f"{BASE}/m/{REAL_SLUG}/video", BASE)
    assert exc_info.value.code == "invalid_link"


def test_parse_rtr_link_bad_slug_shape_rejected():
    with pytest.raises(ContextLinkError) as exc_info:
        parse_rtr_link("Not A Real Slug!!", BASE)
    assert exc_info.value.code == "invalid_slug"


def test_parse_rtr_link_empty_raises():
    with pytest.raises(ContextLinkError) as exc_info:
        parse_rtr_link("", BASE)
    assert exc_info.value.code == "invalid_link"


def test_context_summary_max_is_a_positive_int():
    # Not much to assert about the exact number, but the crud layer
    # depends on this being usable as a length cap.
    assert isinstance(CONTEXT_SUMMARY_MAX, int)
    assert CONTEXT_SUMMARY_MAX > 0
