import re

from app.utils.vtt_parser import (
    decode_vtt_bytes,
    dedupe_rollup_cues,
    is_likely_garbled,
    normalize_speaker_change_marker,
    parse_captions_by_extension,
    parse_srt,
    parse_ttml,
    parse_vtt,
    strip_unknown_caption_markup,
    unescape_caption_entities,
)

from conftest import load_fixture, load_fixture_bytes


def test_parse_vtt_basic_cues():
    content = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.500\n"
        "Hello there.\n\n"
        "00:00:02.500 --> 00:00:04.000\n"
        "Second line."
    )
    cues = parse_vtt(content)
    assert len(cues) == 2
    assert cues[0] == {"start": 1.0, "end": 2.5, "text": "Hello there."}
    assert cues[1]["text"] == "Second line."


def test_parse_vtt_multiline_cue_joins_with_newline():
    content = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nline one\nline two"
    cues = parse_vtt(content)
    assert cues[0]["text"] == "line one\nline two"


def test_parse_vtt_real_simi_valley_fixture():
    # Real captions.vtt fetched live from simivalley.granicus.com/videos/2840
    # (the exact clip BACKLOG_DONE.md documents as real, Spanish-language,
    # originally a non-UTF-8-decode bug -- now valid UTF-8 at the source).
    content = load_fixture("granicus", "simivalley_clip2840_captions.vtt")
    cues = parse_vtt(content)
    assert len(cues) > 100
    assert cues[0]["start"] == 32.0
    assert "llamar esta junta a la orden" in cues[0]["text"]


def test_parse_vtt_skips_standalone_cue_identifier_line():
    # Real bug (2026-08-08), confirmed live on a real Bakersfield, CA
    # eScribe/iSiLIVE meeting: this file numbers its cues on their own
    # line before each timestamp, the same convention SRT uses (WebVTT's
    # spec section 4.1 explicitly allows this as an optional cue
    # identifier). Before this fix, every number was silently absorbed as
    # trailing text onto the *previous* cue ("Hello there.\n2") since
    # parse_vtt only ever recognized "WEBVTT" and blank lines as
    # non-cue-text lines.
    content = (
        "WEBVTT\n\n"
        "1\n"
        "00:00:01.000 --> 00:00:02.500\n"
        "Hello there.\n\n"
        "2\n"
        "00:00:02.500 --> 00:00:04.000\n"
        "Second line."
    )
    cues = parse_vtt(content)
    assert len(cues) == 2
    assert cues[0]["text"] == "Hello there."
    assert cues[1]["text"] == "Second line."


def test_parse_vtt_does_not_mistake_real_short_text_for_an_identifier():
    # A genuinely short cue's text ("Yes.") must not be swallowed just
    # because it's a single short line -- it's only treated as a cue
    # identifier when the *very next* line is itself a real timestamp
    # line, not just any short line.
    content = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:02.000\n"
        "Yes.\n\n"
        "00:00:02.000 --> 00:00:03.000\n"
        "No."
    )
    cues = parse_vtt(content)
    assert [c["text"] for c in cues] == ["Yes.", "No."]


def test_parse_vtt_real_bakersfield_fixture_with_numbered_cues():
    # Real captions.vtt fetched live from a Bakersfield, CA eScribe
    # meeting (Meeting.aspx?Id=981f78d7-8211-4b4b-b066-5f93b4fd5e74),
    # trimmed to its first 25 cues -- this is the first real eScribe
    # sample ever found with actually-populated captions (see BACKLOG.md's
    # prior "content-quality unverified" note) and it's exactly what
    # exposed the numbered-cue-identifier bug above.
    content = load_fixture("escribe", "bakersfield_ccm330_captions.vtt")
    cues = parse_vtt(content)
    assert len(cues) == 25
    assert cues[0]["text"] == "The 330 p. m. meeting of the Bakersfield City Council"
    # None of the real cue text should have a stray trailing number from
    # the next cue's identifier line leaking in.
    assert not any(re.search(r"\n\d+$", c["text"]) for c in cues)


def test_parse_vtt_strips_inline_voice_tags_real_ocfl_fixture():
    # Real captions.vtt fetched live 2026-08-17 from otv.ocfl.net (Orange
    # County FL's live captioning host, discovered via the real
    # netapps.ocfl.net meeting-listing fixture's own vtt links), trimmed to
    # its first 12 cues. Confirms the real, currently-live bug documented
    # in BACKLOG.md: a platform="unknown" meeting parsed via
    # generic_fallback.py -> parse_vtt() (meeting-7ac1da, a different OCFL
    # meeting already archived with this exact same raw <v.Male.spkN
    # SpeakerN> tag shape, where the tags being left in mangled a real
    # person's name into "misbranded rigors") has these tags inline in its
    # real source VTT -- parse_vtt() itself did no tag-stripping at all
    # before this fix.
    content = load_fixture("generic_fallback", "ocfl_bcc071626aa_captions.vtt")
    cues = parse_vtt(content)
    assert len(cues) == 12
    assert (
        cues[0]["text"] == ">> Good morning, everyone.\nAnd welcome all of you to the"
    )
    assert (
        cues[2]["text"] == ">> Budget Work Session, July,\nthe 16th 2026, we're in the"
    )
    # No raw voice tag should survive into any cue's rendered text.
    assert not any("<v." in c["text"] for c in cues)
    assert not any("<" in c["text"] for c in cues)


def test_parse_vtt_skips_note_blocks_synthetic():
    # Real WebVTT NOTE (comment) blocks are a spec-defined construct
    # (section 4.3) confirmed present in this exact shape in a real
    # archived meeting -- Tavares FL CivicClerk BCC meeting, 2024-06-11
    # (tavares-fl-2024-06-11-bcc-regular-board-meeting): its already-parsed
    # stored segments (fetched live from the meeting's public
    # /m/{slug}/transcript.txt export while building this fix) alternate
    # real spoken text with literal `NOTE Confidence: 0.962116034285714`
    # lines, e.g. "Good morning and welcome to the June 11th, NOTE
    # Confidence: 0.962116034285714 2024 meeting of the Board ...". The
    # real source VTT hasn't itself been independently re-fetched (see
    # BACKLOG.md's own caveat on this entry), so this test is synthetic: it
    # reconstructs real WebVTT NOTE-block syntax around real confirmed cue
    # text and the real confidence value seen in production, rather than
    # replaying an actual captured .vtt file byte-for-byte.
    content = (
        "WEBVTT\n\n"
        "NOTE Confidence: 0.962116034285714\n\n"
        "00:00:02.450 --> 00:00:02.480\n"
        "Good morning and welcome to the June 11th,\n\n"
        "NOTE\n"
        "This is a multi-line comment block\n"
        "that should also be skipped entirely.\n\n"
        "00:00:02.480 --> 00:00:02.500\n"
        "2024 meeting of the Board\n\n"
        "NOTE Confidence: 0.962116034285714\n\n"
        "00:00:02.500 --> 00:00:02.510\n"
        "of County Commissioners."
    )
    cues = parse_vtt(content)
    assert len(cues) == 3
    assert cues[0]["text"] == "Good morning and welcome to the June 11th,"
    assert cues[1]["text"] == "2024 meeting of the Board"
    assert cues[2]["text"] == "of County Commissioners."
    assert not any("NOTE" in c["text"] for c in cues)


def test_decode_vtt_bytes_real_blank_placeholder():
    # Real 8-byte "WEBVTT\n\n" placeholder Granicus serves when a meeting
    # was never captioned -- fetched live from napacity.granicus.com's
    # clip 3450 captions.vtt.
    raw = load_fixture_bytes("granicus", "napacity_clip3450_captions.vtt")
    assert raw == b"WEBVTT\n\n"
    assert decode_vtt_bytes(raw) == "WEBVTT\n\n"


def test_decode_vtt_bytes_utf8():
    raw = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHéllo".encode("utf-8")
    assert "Héllo" in decode_vtt_bytes(raw)


def test_decode_vtt_bytes_windows_1252_fallback():
    # 0xe9 alone is invalid UTF-8 but decodes as "é" under windows-1252 --
    # the real failure mode documented for Simi Valley's original bug
    # (a non-UTF-8 byte in an otherwise-plain-text VTT file).
    raw = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nCaf".encode("utf-8") + b"\xe9"
    decoded = decode_vtt_bytes(raw)
    assert decoded.endswith("Café")


def test_decode_vtt_bytes_replaces_when_neither_encoding_fits():
    raw = b"WEBVTT\n\n\x81\x8d"  # undefined in both utf-8 and windows-1252
    decoded = decode_vtt_bytes(raw)
    assert "WEBVTT" in decoded
    assert "�" in decoded


def test_is_likely_garbled_true_for_short_junk_fragments():
    # Mirrors the real Alexandria VA pattern documented in vtt_parser.py:
    # short 1-2 letter junk fragments well above the 6% threshold.
    junk_words = ["tm", "Oa", "sd", "xr", "qp"] * 10
    clean_words = ["the", "meeting", "will", "come", "to", "order"] * 3
    cues = [{"start": 0, "end": 1, "text": " ".join(junk_words + clean_words)}]
    assert is_likely_garbled(cues) is True


def test_is_likely_garbled_false_for_clean_transcript():
    text = (
        "Good evening and welcome to the regular meeting of the city "
        "council. I would like to call this meeting to order and ask "
        "the clerk to please call the roll for all members present "
        "this evening as we begin our agenda for tonight's session."
    )
    cues = [{"start": 0, "end": 1, "text": text}]
    assert is_likely_garbled(cues) is False


def test_is_likely_garbled_false_below_min_sample_size():
    cues = [{"start": 0, "end": 1, "text": "tm Oa sd"}]
    assert is_likely_garbled(cues) is False


def test_is_likely_garbled_true_for_clean_prefix_then_garbled_tail():
    # Real confirmed case (Cincinnati OH, "budget and finance committee"
    # 2023-02-13, see BACKLOG.md and vtt_parser.py's is_likely_garbled
    # docstring): 98,449 chars of real joined cue text that stays clean
    # through roughly the first quarter, then degrades into binary-looking
    # junk for most of what follows. No raw fixture .vtt exists for this
    # meeting (it delegates Legistar -> Granicus, and only the already-
    # rendered plain-text export was available to check against), so this
    # test is built from real text: the clean prefix below is the real
    # opening dialogue and the garbled tail is the real corrupted content,
    # both fetched live from the meeting's public
    # /m/{slug}/transcript.txt export on redtaperecordings.com while
    # building this fix -- only the surrounding structure (splitting into
    # a handful of discrete cues, and interior padding to reproduce the
    # real ~98K-char total length/offsets) is synthetic. Confirmed against
    # this real text that the *old* single-4000-char-prefix sampling gives
    # a ~1.3% junk ratio (misses it, well under the 6% threshold) while
    # the new four-offset sampling gives ~42% (correctly flags it).
    clean_prefix = (
        ">> Councilmember Harris: if councilmembers can take their seats. "
        ">> Councilmember Harris: all right. We will begin. Welcome to "
        "budget and finance. I'm your budget chair, reggie harris. I'm "
        "joined today by PRESIDENT Pro tem parks, and councilmember "
        "warble and councilmember johnson. Vice mayor lemon-kearney, "
        "councilmember owens, councilmember keating and jeffreys, from "
        "the administration, sorry, we can't hear you. sorry about that "
        "I'm mark, a member of the common ground usa, an organization "
        "for the prudent management of land holdings and other public "
        "ownership and this is about the plans to sell off the "
        "cincinnati southern. And just pointing to the best explain I "
        "did a radio show over s"
    )
    garbled_fragment = (
        "6~\x7fkf}IXFpu;f[So1d ko/8#\n:wb0oi>3I7\n]O?3/8ns\"ZeHr/I/w'dx6t\n"
        '"w6tp^Nngzhur+6zg\n^NQn:f&IFRe~dn\x7fDf1!\n\x7fk\ntCu\n'
        "w_MRrHnw6tp^NngzhIXf\nTr+6~g>mGjr+6~g>mGjr+6~g>mGjr+6~g>mGjr+6~"
        'g>Ogm?,f1?Mm?$b\n?Iv^nq>wrc12f\x7f+Df{" c\n0"\nu\x7fk=\n'
        "~LfYf\x7f+Db3qp^s:j\x7fk=g\x7f+6~\x7fkf}IXFpu;f[So1d ko/8#\n"
    )
    # Real total length was 98,449 chars, clean through ~28%; pad with
    # filler (itself alternating real-shaped clean/garbled blocks) so the
    # 0/25/50/75% sample offsets land in the same real regions confirmed
    # above rather than only ever hitting index 0.
    padding_clean = "the meeting will come to order. " * 200
    padding_garbled = garbled_fragment * 40
    full_text = clean_prefix + padding_clean + padding_garbled
    cues = [{"start": 0, "end": 1, "text": full_text}]
    assert is_likely_garbled(cues) is True


def test_normalize_shouting_caption_recases_all_caps_track():
    content = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "THE JULY MEETING OF THE CITY COUNCIL WILL NOW COME TO ORDER "
        "PLEASE STAND FOR THE PLEDGE OF ALLEGIANCE TO THE FLAG OF THE "
        "UNITED STATES OF AMERICA.\n\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "MADAM CLERK PLEASE CALL THE ROLL FOR ALL MEMBERS PRESENT."
    )
    cues = parse_vtt(content)
    joined = " ".join(c["text"] for c in cues)
    assert joined != joined.upper()
    assert cues[0]["text"].startswith("The july meeting")


def test_normalize_shouting_caption_leaves_normal_case_alone():
    content = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "The meeting will now come to order, please stand for the "
        "pledge of allegiance to the flag."
    )
    cues = parse_vtt(content)
    assert cues[0]["text"].startswith("The meeting will now come to order")


def test_parse_vtt_replaces_literal_speaker_change_entity_with_marker():
    # Real structure confirmed live: YouTube's own raw auto-caption VTT
    # contains the literal 8-character string "&gt;&gt;" as real cue text
    # at a new speaker's first cue, not an actual ">" character this app
    # is mis-escaping.
    content = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "&gt;&gt; Welcome everyone. Today is March the 3rd."
    )
    cues = parse_vtt(content)
    assert cues[0]["text"] == "» Welcome everyone. Today is March the 3rd."


def test_normalize_speaker_change_marker_only_matches_literal_prefix():
    cues = [
        {"start": 0, "end": 1, "text": "&gt;&gt; Next item on the agenda."},
        {"start": 1, "end": 2, "text": "Please see &gt;&gt; the linked agenda."},
        {"start": 2, "end": 3, "text": "No marker here at all."},
    ]
    normalize_speaker_change_marker(cues)
    assert cues[0]["text"] == "» Next item on the agenda."
    # Not at the very start of the cue -- left untouched, matching a real
    # ampersand/angle-bracket mention elsewhere in a caption staying inert.
    assert cues[1]["text"] == "Please see &gt;&gt; the linked agenda."
    assert cues[2]["text"] == "No marker here at all."


def test_unescape_caption_entities_handles_mid_cue_and_other_entities():
    # Real gap fixed 2026-08-11: the start-anchored marker regex above only
    # ever catches "&gt;&gt;" at the very start of a cue -- a mid-cue
    # occurrence, or any other pre-escaped entity, used to double-escape
    # through Jinja's autoescape into a visible "&gt;&gt;"/"&amp;"-style
    # artifact on the page instead of the real character.
    cues = [
        {"start": 0, "end": 1, "text": "Please see &gt;&gt; the linked agenda."},
        {"start": 1, "end": 2, "text": "Smith &amp; Jones, LLC"},
        {
            "start": 2,
            "end": 3,
            "text": "She said &quot;hello&quot; and &#39;goodbye&#39;.",
        },
    ]
    unescape_caption_entities(cues)
    assert cues[0]["text"] == "Please see >> the linked agenda."
    assert cues[1]["text"] == "Smith & Jones, LLC"
    assert cues[2]["text"] == "She said \"hello\" and 'goodbye'."


def test_unescape_caption_entities_leaves_literal_ampersand_alone():
    # A caption that legitimately contains a bare "&" (not a real entity
    # pattern) must pass through unchanged -- this is the exact risk the
    # narrow marker-only fix was originally scoped around avoiding.
    cues = [{"start": 0, "end": 1, "text": "Bed & Breakfast on Main St."}]
    unescape_caption_entities(cues)
    assert cues[0]["text"] == "Bed & Breakfast on Main St."


def test_parse_vtt_unescapes_mid_cue_entity_after_marker_fix_runs():
    # End-to-end through parse_vtt: the start-of-cue "&gt;&gt;" still
    # becomes the real "»" marker (unaffected by the general fix running
    # after it), while an unrelated mid-cue entity in the same track gets
    # unescaped too.
    content = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "&gt;&gt; Welcome. Smith &amp; Jones will present next."
    )
    cues = parse_vtt(content)
    assert cues[0]["text"] == "» Welcome. Smith & Jones will present next."


def test_dedupe_rollup_cues_collapses_youtube_style_rollup():
    # Real structure confirmed live against a YouTube auto-caption track
    # (documented in vtt_parser.py's dedupe_rollup_cues docstring).
    cues = [
        {
            "start": 1.199,
            "end": 3.75,
            "text": "\nmost permanent supportive housing takes",
        },
        {
            "start": 3.75,
            "end": 3.76,
            "text": "most permanent supportive housing takes\n",
        },
        {
            "start": 3.76,
            "end": 5.749,
            "text": "most permanent supportive housing takes\nfive to seven years",
        },
    ]
    result = dedupe_rollup_cues(cues)
    texts = [c["text"] for c in result]
    # First two source cues both settle on the same last line ("...takes"),
    # so they collapse into one segment; the third cue's last line ("five
    # to seven years") is a new line, not a growing prefix of the first, so
    # it starts a second segment rather than merging -- no duplicated text
    # anywhere, which is the bug this function fixes.
    assert texts == [
        "most permanent supportive housing takes",
        "five to seven years",
    ]
    assert len(texts) == len(set(texts))


def test_dedupe_rollup_cues_strips_tags():
    cues = [{"start": 0, "end": 1, "text": "<c>hello</c> <c>world</c>"}]
    result = dedupe_rollup_cues(cues)
    assert result[0]["text"] == "hello world"


def test_parse_srt_strips_sequence_numbers_synthetic():
    # Minimal synthetic case isolating the exact bug: feeding raw SRT into
    # parse_vtt directly corrupts every cue after the first by appending
    # the *next* cue's sequence-number line to the end of the current
    # cue's text (a bare "2"/"3" line doesn't match the timestamp regex,
    # so parse_vtt's loop treats it as more text for the still-open cue).
    content = (
        "1\n"
        "00:00:00,000 --> 00:00:02,000\n"
        "Hello there.\n\n"
        "2\n"
        "00:00:02,000 --> 00:00:04,000\n"
        "Second line."
    )
    cues = parse_srt(content)
    assert cues == [
        {"start": 0.0, "end": 2.0, "text": "Hello there."},
        {"start": 2.0, "end": 4.0, "text": "Second line."},
    ]


def test_parse_srt_real_emporia_fixture():
    # Real captions.srt fetched live from emporiaks.api.civicclerk.com
    # event 585 (user-supplied real-world example, 2026-08-08) -- the
    # first real CivicClerk sample found with populated closed captions,
    # and confirmed to be SRT format, not VTT.
    content = load_fixture("civicclerk", "emporiaks_585_captions.srt")
    cues = parse_srt(content)
    assert len(cues) == 3677
    # No cue's text is left over as a bare sequence number -- the exact
    # corruption a naive parse_vtt(raw_srt) call would produce.
    assert not any(re.fullmatch(r"\d+", c["text"].strip()) for c in cues)
    assert cues[3]["text"] == "Meeting to order."


# --- parse_ttml -------------------------------------------------------
# Not verified against a real captured file from any platform this app
# supports (unlike parse_srt's real Emporia fixture above) -- no
# CivicClerk/Granicus/Swagit/CA Legislature sample has ever used TTML.
# Built and tested against the W3C TTML spec's own documented shape.


def test_parse_ttml_clock_time():
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<tt xmlns="http://www.w3.org/ns/ttml" xml:lang="en">'
        "<body><div>"
        '<p begin="00:00:01.000" end="00:00:03.500">Hello there.</p>'
        '<p begin="00:00:03.500" end="00:00:05.000">Second line.</p>'
        "</div></body></tt>"
    )
    cues = parse_ttml(content)
    assert cues == [
        {"start": 1.0, "end": 3.5, "text": "Hello there."},
        {"start": 3.5, "end": 5.0, "text": "Second line."},
    ]


def test_parse_ttml_offset_time_seconds_and_ms():
    content = (
        '<tt xmlns="http://www.w3.org/ns/ttml">'
        "<body><div>"
        '<p begin="1.5s" end="3.2s">Seconds offset.</p>'
        '<p begin="3200ms" end="4000ms">Milliseconds offset.</p>'
        "</div></body></tt>"
    )
    cues = parse_ttml(content)
    assert cues == [
        {"start": 1.5, "end": 3.2, "text": "Seconds offset."},
        {"start": 3.2, "end": 4.0, "text": "Milliseconds offset."},
    ]


def test_parse_ttml_handles_namespace_prefix():
    # Some vendors prefix TTML elements (e.g. tt:p) instead of using a
    # default namespace -- ElementTree renders both as "{uri}p", so the
    # namespace-agnostic tag match must work for either.
    content = (
        '<tt:tt xmlns:tt="http://www.w3.org/ns/ttml">'
        "<tt:body><tt:div>"
        '<tt:p begin="00:00:00.000" end="00:00:01.000">Prefixed.</tt:p>'
        "</tt:div></tt:body></tt:tt>"
    )
    cues = parse_ttml(content)
    assert cues == [{"start": 0.0, "end": 1.0, "text": "Prefixed."}]


def test_parse_ttml_strips_nested_span_markup_and_collapses_whitespace():
    content = (
        '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
        '<p begin="1.0s" end="2.0s">Hello\n  <span>there</span>,\n  world.</p>'
        "</div></body></tt>"
    )
    cues = parse_ttml(content)
    assert cues[0]["text"] == "Hello there, world."


def test_parse_ttml_skips_cue_with_unresolvable_frame_based_time():
    # Frame-based ("40f") timing needs a frame rate this function has no
    # access to -- skipped rather than guessed, not silently wrong.
    content = (
        '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
        '<p begin="40f" end="80f">Frame-based, skipped.</p>'
        '<p begin="1.0s" end="2.0s">Real cue, kept.</p>'
        "</div></body></tt>"
    )
    cues = parse_ttml(content)
    assert cues == [{"start": 1.0, "end": 2.0, "text": "Real cue, kept."}]


def test_parse_ttml_malformed_xml_returns_empty_not_raises():
    assert parse_ttml("<tt><body><div><p>unclosed") == []
    assert parse_ttml("not xml at all") == []


# --- strip_unknown_caption_markup --------------------------------------


def test_strip_unknown_caption_markup_sbv_style():
    content = (
        "0:00:01.500,0:00:03.200\n"
        "Hello there.\n\n"
        "0:00:03.200,0:00:05.000\n"
        "Second line.\n"
    )
    assert strip_unknown_caption_markup(content) == "Hello there.\nSecond line."


def test_strip_unknown_caption_markup_microdvd_style():
    content = "{100}{200}Hello there.\n{200}{300}Second line."
    assert strip_unknown_caption_markup(content) == "Hello there.\nSecond line."


def test_strip_unknown_caption_markup_sami_style():
    content = (
        "<SAMI><BODY><SYNC Start=1500><P Class=ENCC>Hello there.\n"
        "<SYNC Start=3200><P Class=ENCC>Second line.\n"
        "</BODY></SAMI>"
    )
    assert strip_unknown_caption_markup(content) == "Hello there.\nSecond line."


def test_strip_unknown_caption_markup_drops_srt_style_sequence_numbers_too():
    content = "1\n00:00:00,000 --> 00:00:02,000\nBare number test.\n"
    assert strip_unknown_caption_markup(content) == "Bare number test."


def test_strip_unknown_caption_markup_recases_all_caps_track():
    # Real gap fixed 2026-08-11: normalize_shouting_caption() only ever
    # ran on structured (VTT/SRT/TTML) cue lists -- an ALL-CAPS SBV/SUB/
    # SMI/plain-.txt track stayed ALL CAPS unconditionally, unlike every
    # other caption format. Same shouting heuristic, applied via the
    # shared _normalize_shouting_text() helper.
    content = (
        "0:00:01.500,0:00:03.200\n"
        "THE JULY MEETING OF THE CITY COUNCIL WILL NOW COME TO ORDER "
        "PLEASE STAND FOR THE PLEDGE OF ALLEGIANCE TO THE FLAG.\n\n"
        "0:00:03.200,0:00:05.000\n"
        "MADAM CLERK PLEASE CALL THE ROLL FOR ALL MEMBERS PRESENT.\n"
    )
    result = strip_unknown_caption_markup(content)
    assert result != result.upper()
    assert result.startswith("The july meeting")


def test_strip_unknown_caption_markup_leaves_short_all_caps_alone():
    # Under the shouting heuristic's 40-letter sample minimum -- stays
    # untouched rather than guessing off too little signal, matching
    # normalize_shouting_caption()'s own threshold behavior.
    content = "0:00:01.000,0:00:02.000\nHELLO.\n"
    assert strip_unknown_caption_markup(content) == "HELLO."


def test_strip_unknown_caption_markup_unescapes_entities():
    # Real gap fixed 2026-08-11: the fallback path (SBV/SUB/SMI/plain-.txt)
    # had no cue-level text normalization of any kind before this -- a
    # pre-escaped entity here would double-escape through Jinja the same
    # way an unfixed VTT/SRT cue would.
    content = "0:00:01.000,0:00:02.000\nSmith &amp; Jones &quot;LLC&quot;\n"
    assert strip_unknown_caption_markup(content) == 'Smith & Jones "LLC"'


def test_strip_unknown_caption_markup_unescape_does_not_resurrect_stripped_tags():
    # A caption source that legitimately meant an already-escaped fake tag
    # as literal text (not a real HTML tag) shouldn't have that text
    # silently deleted -- unescaping only happens *after* tag-stripping
    # here, so this content is never re-interpreted as a tag to strip.
    content = "0:00:01.000,0:00:02.000\nShe wrote &lt;i&gt;in italics&lt;/i&gt; on the form.\n"
    assert (
        strip_unknown_caption_markup(content)
        == "She wrote <i>in italics</i> on the form."
    )


# --- parse_captions_by_extension ---------------------------------------


def test_parse_captions_by_extension_structured_formats():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi."
    cues, text = parse_captions_by_extension("https://x.com/a.vtt", vtt)
    assert cues and text is None

    srt = "1\n00:00:01,000 --> 00:00:02,000\nHi."
    cues, text = parse_captions_by_extension("https://x.com/a.srt", srt)
    assert cues and text is None

    ttml = '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1.0s" end="2.0s">Hi.</p></div></body></tt>'
    cues, text = parse_captions_by_extension("https://x.com/a.dfxp", ttml)
    assert cues and text is None


def test_parse_captions_by_extension_xml_probes_ttml_before_falling_back_to_text():
    ttml = '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1.0s" end="2.0s">Real TTML.</p></div></body></tt>'
    cues, text = parse_captions_by_extension("https://x.com/a.xml", ttml)
    assert cues == [{"start": 1.0, "end": 2.0, "text": "Real TTML."}]
    assert text is None

    non_ttml_xml = "<data><line>Hello there.</line></data>"
    cues, text = parse_captions_by_extension("https://x.com/a.xml", non_ttml_xml)
    assert cues is None
    assert text == "Hello there."


def test_parse_captions_by_extension_text_fallback_formats():
    sbv = "0:00:01.000,0:00:02.000\nHi there."
    cues, text = parse_captions_by_extension("https://x.com/a.sbv", sbv)
    assert cues is None
    assert text == "Hi there."


def test_parse_captions_by_extension_binary_format_returns_nothing():
    cues, text = parse_captions_by_extension(
        "https://x.com/a.scc", "Scenarist_SCC V1.0\n\n00:00:01:00 9420"
    )
    assert cues is None
    assert text is None


def test_parse_captions_by_extension_query_string_does_not_break_extension_detection():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi."
    cues, text = parse_captions_by_extension("https://x.com/a.vtt?token=abc123", vtt)
    assert cues and text is None
