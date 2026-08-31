import re

from langdetect import detect as _detect_language

from app.utils.vtt_parser import (
    _is_rollup_pair,
    _looks_like_rollup,
    _rollup_lines,
    decode_vtt_bytes,
    dedupe_rollup_cues,
    detect_language_from_texts,
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


def test_is_likely_garbled_false_for_real_bilingual_chula_vista_transcript():
    # Real bug, fixed 2026-08-31 (BACKLOG.md's "Likely a false-positive
    # garbled-marker" entry): Chula Vista CA's 2026-05-19 city council
    # meeting (eScribe, version 816) has a real, coherent Spanish
    # transcript that the old ASCII-only word tokenizer false-flagged as
    # garbled -- accented characters (sesión, está, día) split real words
    # into spurious 1-2 letter fragments, and _COMMON_SHORT_WORDS had no
    # Spanish entries either. This fixture is a real excerpt (first 25,000
    # of ~165,000 chars, timestamps stripped) fetched live from the
    # meeting's public /m/{slug}/transcript.txt export on
    # redtaperecordings.com while building this fix -- not synthetic. The
    # old tokenizer scored the full real transcript 35.6% junk (would
    # false-flag; threshold is 6%); this fix brings it to well under
    # threshold when the caller passes the already-detected lang="es".
    text = load_fixture("escribe", "chula_vista_public_comments_transcript_excerpt.txt")
    cues = [{"start": 0, "end": 1, "text": text}]
    assert is_likely_garbled(cues, lang="es") is False


def test_is_likely_garbled_still_true_for_genuinely_garbled_spanish():
    # The lang="es" allowlist must not become a blanket bypass for
    # non-English content -- Fountain Valley's real genuinely-garbled case
    # is itself non-English-detected (misdetected as 'pt'), so a
    # lang-based skip would have silenced that true positive too. This
    # reuses the real Alexandria-shaped junk pattern (short 1-2 letter
    # fragments well above threshold) with lang="es" passed, to confirm
    # the allowlist addition alone doesn't blind detection of genuine
    # corruption just because the caller detected a non-English language.
    junk_words = ["tm", "Oa", "sd", "xr", "qp"] * 10
    clean_words = ["la", "el", "de", "en", "es"] * 3
    cues = [{"start": 0, "end": 1, "text": " ".join(junk_words + clean_words)}]
    assert is_likely_garbled(cues, lang="es") is True


def test_is_likely_garbled_unaffected_by_apostrophe_contractions():
    # The tokenizer switched from an ASCII [A-Za-z0-9']+ char class to a
    # Unicode-letter-aware one (for the Chula Vista fix above) that
    # excludes digits/underscore rather than allow-listing ASCII letters --
    # confirm contractions ("don't", "I'm", "can't") still count as one
    # word each rather than splitting off a spurious 1-letter fragment
    # ("t", "m") that would inflate the junk ratio on ordinary English.
    text = (
        "I'm not sure we'll finish tonight, but let's try. Councilmember, "
        "don't forget to call the roll -- we can't start without it. "
        "It's getting late and I think we're all ready to adjourn soon."
    )
    cues = [{"start": 0, "end": 1, "text": text * 5}]
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


def test_sentence_case_does_not_capitalize_after_a_bare_line_wrap():
    # Real confirmed case (2026-08-28, BACKLOG_DONE.md): Antioch CA
    # CivicClerk 2026-03-10 -- a de-shouted two-line cue used to read
    # "...our regular city\nCouncil meeting..." because a bare "\n" line
    # wrap was treated as a sentence boundary. A line wrap is mid-sentence,
    # not a new sentence.
    from app.utils.vtt_parser import _sentence_case

    assert (
        _sentence_case(
            "WELCOME TO OUR REGULAR CITY\nCOUNCIL MEETING OF MARCH THE 10TH, 2026."
        )
        == "Welcome to our regular city\ncouncil meeting of march the 10th, 2026."
    )
    # A real punctuation-then-newline boundary must still capitalize --
    # \s+ after [.!?] already spans a bare \n, so nothing regresses here.
    assert (
        _sentence_case("GOOD EVENING.\nWELCOME EVERYONE.")
        == "Good evening.\nWelcome everyone."
    )


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


def test_dedupe_rollup_cues_real_tacoma_granicus_rollup_fixture():
    # Real Granicus captions.vtt for Tacoma WA city council 2026-01-06
    # (cityoftacoma.granicus.com/videos/7460/captions.vtt, fetched live
    # 2026-08-21) -- the exact meeting BACKLOG.md named as the worst live
    # instance of this bug. The full file is 21,240 cues / 1.5MB; this
    # fixture is two verbatim excerpts of it (00:00:05-00:00:14 and
    # 01:12:11-01:12:17), untouched apart from the cues in between being
    # dropped, which is why the second excerpt's timestamps jump.
    #
    # Granicus's shape is NOT YouTube's: a single fixed-width (~63 char)
    # ticker line that grows word-by-word and then drops words off the
    # *front*. The old whole-string prefix test handles the growth and then
    # fails at every front-drop -- which is where ">> Councilmember Hines: "
    # disappears mid-run below, and why the live page showed 13 successive
    # segments each re-printing the whole sentence so far.
    content = load_fixture("granicus", "tacoma_clip7460_captions.vtt")
    cues = parse_vtt(content)
    assert len(cues) == 45

    segments = dedupe_rollup_cues(cues)
    assert segments == [
        {"start": 5.907, "end": 6.474, "text": "JUST A SECOND."},
        {
            "start": 6.474,
            "end": 11.279,
            "text": (
                ">> Councilmember Hines: WE WILL GET EVERYONE SWORN IN SO WE "
                "CAN BEGIN OUR COUNCIL MEETING HERE THIS EVENING."
            ),
        },
        {"start": 11.279, "end": 13.546, "text": ">> HELLO EVERYONE."},
        {"start": 13.748, "end": 14.249, "text": "THANK YOU"},
        {
            "start": 4331.328,
            "end": 4331.595,
            "text": "QUESTIONS OR COMMENTS FROM THE COUNCIL?",
        },
        # The source emits a transient scrolled window ("HAVE ONE.") and then
        # reverts to the fuller one on the very next cue -- a real ticker is
        # not strictly monotone. Matching against a rolling tail of the
        # reconstructed text absorbs that; matching only against the previous
        # cue re-duplicates it.
        {
            "start": 4331.595,
            "end": 4333.931,
            "text": ">> Councilmember Sadalge: I HAVE ONE.",
        },
        {
            "start": 4333.931,
            "end": 4335.9,
            "text": ">> Mayor Ibsen: COUNCILMEMBER SADALGE?",
        },
        {"start": 4335.9, "end": 4337.1, "text": "11 I JUST"},
    ]

    # No segment repeats another's text, and none of them is a growing
    # prefix of the next -- the two shapes the live bug produced.
    texts = [s["text"] for s in segments]
    assert len(texts) == len(set(texts))
    assert not any(b.startswith(a) for a, b in zip(texts, texts[1:]))

    # Segment granularity matters here specifically because this is a
    # deep-link product: an unbounded "extend the open segment's end time"
    # merge would have collapsed the whole 8-second opening run into one
    # segment, so every timestamp on the page would point at the top of a
    # blob. Longest segment on the *full* 2h16m file is 250 chars / 28.3s,
    # median 65 chars / 4.8s.
    assert max(len(s["text"]) for s in segments) < 240
    assert all(s["end"] >= s["start"] for s in segments)


def test_dedupe_rollup_cues_leaves_real_non_rollup_track_untouched():
    # Real Peel Region ON eScribe/iSiLIVE captions (already in the suite as
    # that adapter's populated-captions fixture) -- ordinary
    # one-cue-per-line captions, not roll-up. dedupe_rollup_cues() is now
    # called from the shared parse_captions_by_extension() dispatch and from
    # escribe.py, so "does nothing to a normal track" is load-bearing, not
    # incidental. Measured across 15 real caption files from 6 platforms,
    # the adjacent-pair overlap ratio the gate keys on is <= 0.007 on every
    # non-roll-up track and >= 0.495 on every roll-up one.
    cues = parse_vtt(load_fixture("escribe", "peel_region_captions.vtt"))
    assert len(cues) == 20
    assert dedupe_rollup_cues(cues) == cues


def test_dedupe_rollup_cues_real_civicclerk_two_line_rollup_fixture():
    # Real CivicClerk captions.srt for Antioch CA city council 2026-03-10
    # (cpmedia.azureedge.net/antiochca/ClosedCaption/..., reached by
    # re-resolving the live antiochca.portal.civicclerk.com/event/18/media
    # page 2026-08-21) -- the CivicClerk instance BACKLOG.md named. Full file
    # is 5,481 cues / 482KB and collapses 275KB of cue text down to 135KB;
    # this fixture is a verbatim 60-cue excerpt of it.
    #
    # Third real roll-up shape, and the one that motivates case-folded
    # comparison: the previous line is promoted to the top of a two-line cue
    # with no blank-line alternation. Before the 2026-08-28 _sentence_case()
    # fix (BACKLOG_DONE.md), the ALL-CAPS de-shouting wrongly capitalised
    # after every bare "\n" line wrap, so the *same words* read
    # "Councilmember to move number" as one cue's second line and
    # "councilmember to move number" as the next cue's first -- case-
    # sensitive matching dropped this track's measured roll-up ratio from
    # 0.451 to 0.111, under the detection gate entirely. Fixed at the
    # source now: a line wrap is correctly left lowercase mid-sentence on
    # both sides, so the two instances match exactly. The case-folded
    # comparison this test originally existed to pin stays in place as a
    # safety net (real sources may still emit genuine case drift some
    # other way), so this fixture is kept as a real-data regression guard
    # even though it no longer exercises the fold itself.
    content = load_fixture("civicclerk", "antiochca_event18_captions.srt")
    cues = parse_srt(content)
    assert len(cues) == 60
    assert cues[0]["text"] == "I would like to have a\ncouncilmember to move number"
    assert (
        cues[1]["text"]
        == "councilmember to move number\nfive to number 10, I know these"
    )

    segments = dedupe_rollup_cues(cues)
    assert [s["text"] for s in segments][:6] == [
        "I would like to have a",
        "councilmember to move number",
        "five to number 10, I know these",
        "meetings usually go long so I",
        "just wanted to get that moved",
        "up.",
    ]
    # 60 cues carry 120 caption lines, every one of which appears twice in
    # the source; the reconstruction emits each exactly once.
    assert len(segments) == 61
    joined = " ".join(s["text"] for s in segments)
    assert (
        "councilmember to move number councilmember to move number"
        not in joined.lower()
    )


def test_dedupe_rollup_cues_real_youtube_autocaption_fixture():
    # Real YouTube auto-caption track for Philadelphia City Council's
    # "Committee on Education" 08-06-26 (video 5LZqoNDRMYk, fetched via
    # yt-dlp 2026-08-21). Full track is 13,111 cues / 2.1MB; this is a
    # verbatim 12-cue excerpt spanning 00:01:30-00:01:41.
    #
    # Two things it pins at once. (1) The classic growing shape this
    # function was originally written for still collapses correctly.
    # (2) The speaker-marker fold: normalize_speaker_change_marker() only
    # rewrites "&gt;&gt;" anchored at the *start* of a cue, so YouTube's own
    # source produces "» We can't hear you..." in one cue and ">> We can't
    # hear you..." in the next for the same speech. Without folding the two
    # spellings together, every speaker change re-emits its whole first line
    # a second time.
    content = load_fixture("youtube", "phila_education_5LZqoNDRMYk_captions.vtt")
    cues = parse_vtt(content)
    assert len(cues) == 12
    assert cues[4]["text"].startswith("» We can't hear you.")
    assert "\n[music] the mic." in cues[5]["text"]

    segments = dedupe_rollup_cues(cues)
    assert [s["text"] for s in segments] == [
        "are present will communicate your",
        "present by saying I.",
        ">> We can't hear you. You got to speak to",
        "[music] the mic. Please cut the mic on.",
        ">> Vice Chair Anthony Phillips",
        ">> present.",
        ">> Members, Council Member Esquila,",
    ]


def test_dedupe_rollup_cues_real_escribe_single_word_rollup_fixture():
    # Real eScribe/iSiLIVE captions.vtt for Essex County ON council
    # 2025-12-03 (video.isilive.ca/countyofessex/..., reached by re-resolving
    # the live coe-pub.escribemeetings.com meeting page 2026-08-21) -- the
    # eScribe instance BACKLOG.md named. Full file is 11,627 cues / 746KB and
    # collapses 298KB of cue text down to 231KB; this is a verbatim 18-cue
    # excerpt.
    #
    # Fourth real roll-up shape, and the one that sets the detection floor:
    # this source previews only the *next* line's first word, often as a
    # standalone stub cue of its own, so the overlap between adjacent lines
    # is a single word. A two-shared-words rule scores this track 0.155 --
    # below the gate, i.e. the bug stays unfixed -- against 0.401 for the
    # one-word-of-4+-characters rule the code actually uses.
    content = load_fixture("escribe", "essexcounty_rcc_20251203_captions.vtt")
    cues = parse_vtt(content)
    assert len(cues) == 18

    segments = dedupe_rollup_cues(cues)
    assert [s["text"] for s in segments] == [
        "I would like to call the december third 2025 essex county",
        "council meeting to order.",
        "council is gathered this morning",
        "to deliberate the 2026 budget.",
        "we will invite everyone to join",
        "council and administration as",
        "we take this time for a moment of",
        # The stub cue "   REFLECTION" is followed by "REFLECTION." -- same
        # word, and the punctuated spelling is the one that survives.
        "reflection.",
        "that will lead into the playing",
        "of our national anthem.",
        "[o canada playing, instrumental]",
    ]


def test_looks_like_rollup_flags_real_corpus_scale_youtube_double_marker_cluster():
    # BACKLOG.md's WO-34 follow-up: the 2026-08-30 production sweep
    # (scripts/dedupe_rollup_transcripts.py, report saved at
    # scripts/rollup_dedupe_report.json -- real Archive pages, not a
    # fixture built from prose) found a fifth real roll-up shape distinct
    # from the four WO-34 fixtures above: a YouTube auto-caption track
    # behind a CivicWeb or Municode portal that emits each speaker-change
    # *line* twice in immediate succession -- once with the raw ">>"
    # marker, once with the "»" our own normalize_speaker_change_marker()
    # already folds it to (see that function's docstring) -- with no
    # scrolling/growing window around it, unlike the classic YouTube shape
    # test_dedupe_rollup_cues_real_youtube_autocaption_fixture already
    # pins. That makes it a much smaller defect: this cluster retains
    # ~0.80 of its characters against ~0.07-0.12 for the Granicus ticker
    # shape, and its 8 real affected pages score 0.2023-0.2445 -- close to
    # but still above _ROLLUP_PAIR_RATIO_MIN's 0.20 gate, a far thinner
    # margin than WO-34's original 0.048-vs-0.401 gap.
    #
    # This excerpt is the real captured "before" text for
    # town-of-rye-2026-07-21-rye-town-park-commission-21-jul-2026
    # (townofryeny.civicweb.net), exactly as the sweep's dry run recorded
    # it -- cue timestamps aren't preserved by that report (it only
    # samples 8 lines of text), so they're synthesized here as sequential
    # integers; only the text is real. The full real page (not reproduced
    # here) is ~250 lines and scores 0.2163 end to end; this 8-line
    # excerpt is denser in duplicate pairs than the full page average (2
    # of its 7 adjacent pairs overlap, against roughly 1 in 5 site-wide),
    # so its own ratio runs higher -- the assertion below only pins that
    # it clears the gate with real margin to spare while staying well
    # under the classic shapes' 0.401+ "confident" band, not that it
    # reproduces the exact site-wide number.
    texts = [
        "Ready.",
        "Do you have this on your system?",
        "Once",
        ">> What's that?",
        "» What's that?",
        ">> My board is the old one.",
        "» My board is the old one.",
        ">> Welcome everybody to the Rye Town Park",
    ]
    cues = [
        {"start": float(i), "end": float(i + 1), "text": t} for i, t in enumerate(texts)
    ]

    ratio = _rollup_ratio(cues)
    assert 0.20 <= ratio < 0.401
    assert _looks_like_rollup(_rollup_lines(cues))


def _rollup_ratio(cues):
    """Local re-implementation of scripts/dedupe_rollup_transcripts.py's
    rollup_ratio(), which isn't importable here without pulling in that
    script's own module-level aiohttp/argparse setup. Deliberately mirrors
    it exactly (same _is_rollup_pair-based loop) so this test's number
    means the same thing as the one the production sweep reported."""
    pairs = hits = 0
    previous = None
    for _cue, line, _is_last in _rollup_lines(cues):
        words = line.split()
        if previous is not None:
            pairs += 1
            if _is_rollup_pair(previous, words):
                hits += 1
        previous = words
    return hits / pairs if pairs else 0.0


def test_dedupe_rollup_cues_collapses_real_youtube_double_marker_duplicate_pairs():
    # Same real cluster as the test above, verifying dedupe_rollup_cues()'s
    # actual output against the production sweep's own recorded "after"
    # text for townofryeny.civicweb.net (CivicWeb/YouTube, confirmed live
    # via scripts/dedupe_rollup_transcripts.py's --apply gate, which only
    # ever promotes a rewrite that itself no longer scores as roll-up).
    # This is the regression guard: today's code already collapses this
    # shape correctly (the fold in _fold_words handles ">>"/"»"
    # generically, the same mechanism the classic YouTube fixture above
    # exercises at a bigger scale) -- there is no separate detector to
    # build here, only this test to keep it that way.
    rye_texts = [
        "Ready.",
        "Do you have this on your system?",
        "Once",
        ">> What's that?",
        "» What's that?",
        ">> My board is the old one.",
        "» My board is the old one.",
        ">> Welcome everybody to the Rye Town Park",
    ]
    rye_cues = [
        {"start": float(i), "end": float(i + 1), "text": t}
        for i, t in enumerate(rye_texts)
    ]
    assert [c["text"] for c in dedupe_rollup_cues(rye_cues)] == [
        "Ready.",
        "Do you have this on your system?",
        "Once",
        ">> What's that?",
        ">> My board is the old one.",
        ">> Welcome everybody to the Rye Town Park",
    ]

    # Second real tenant (wcwd.civicweb.net, real ratio 0.2445), at the
    # pair level rather than the whole-page gate: this 8-line sample has
    # only one duplicate pair in it (the report only saves an 8-line
    # excerpt per page, not the full ~250-line track), which on its own
    # scores 0.14 -- under the gate on this short a sample even though the
    # real full page clears it. That is expected, not a bug: the gate is a
    # whole-track statistic, and an isolated short excerpt is exactly what
    # loses that statistical power (see this file's real Tacoma/Antioch/
    # Essex fixtures above, which are all much longer for the same
    # reason). What *is* real and testable from this excerpt alone is that
    # the fold recognizes the ">>"/"»" pair as a repeat, which is the
    # specific mechanism this cluster depends on.
    assert _is_rollup_pair(
        ">> Do I need to do that again?".split(),
        "» Do I need to do that again?".split(),
    )


def test_parse_captions_by_extension_dedupes_rollup_captions():
    # The wiring itself: Granicus/CivicClerk/Swagit/CA-Legislature/Aurora/
    # Seattle Channel/generic-fallback all reach captions through this one
    # dispatch, which is why fixing dedupe per-adapter is what left them
    # broken while YouTube and Viebit were fine.
    content = load_fixture("granicus", "tacoma_clip7460_captions.vtt")
    cues, fallback_text = parse_captions_by_extension(
        "https://cityoftacoma.granicus.com/videos/7460/captions.vtt", content
    )
    assert fallback_text is None
    assert len(cues) == 8
    assert cues[1]["text"].endswith("BEGIN OUR COUNCIL MEETING HERE THIS EVENING.")


def test_detect_language_votes_across_whole_transcript_not_just_head():
    # Synthetic *composition* of two real transcripts, not invented text:
    # the head is the real Simi Valley Spanish caption track (Granicus clip
    # 2840) and the body is the real Tacoma English one, standing in for the
    # recurring real pattern BACKLOG.md documents -- a short non-English or
    # dead-air opening stretch (an invocation, a proclamation, music before
    # the gavel) inside an otherwise clearly-English multi-hour meeting.
    # What is *not* synthetic is the failure: two real live pages,
    # /m/meeting-00bbd1 (Lincoln City OR) and /m/meeting-d09fc0 (Moraine
    # City OH), were both labelled Welsh ('cy') this way. Those two pages
    # can't be used as fixtures directly -- the mislabel was produced by a
    # borderline langdetect call on their opening chunk, and langdetect is
    # now seeded, so the exact wrong answer isn't reproducible from the
    # stored text. This composition reproduces the *mechanism* instead, and
    # pins it with the head-only assertion below.
    spanish = [
        c["text"]
        for c in parse_vtt(load_fixture("granicus", "simivalley_clip2840_captions.vtt"))
    ]
    english = [
        c["text"]
        for c in parse_vtt(load_fixture("granicus", "tacoma_clip7460_captions.vtt"))
    ] * 40
    texts = spanish[:60] + english

    # The old implementation's exact sample: first 2000 chars of the join.
    # It really would have called this whole transcript Spanish.
    assert _detect_language(" ".join(texts)[:2000]) == "es"
    # The length-weighted vote across the whole thing gets it right.
    assert detect_language_from_texts(texts) == "en"


def test_detect_language_still_returns_es_for_a_genuinely_spanish_transcript():
    # The Simi Valley guard the WO-34 language change must not break: real
    # Spanish content on a track the page labels srclang="en".
    texts = [
        c["text"]
        for c in parse_vtt(load_fixture("granicus", "simivalley_clip2840_captions.vtt"))
    ]
    assert detect_language_from_texts(texts) == "es"


def test_detect_language_short_transcript_is_unchanged_single_sample():
    # Under _LANG_CHUNK_CHARS there is exactly one chunk, so short/scraped
    # tracks behave exactly as they did before the vote was added.
    texts = [
        c["text"]
        for c in parse_vtt(load_fixture("escribe", "peel_region_captions.vtt"))
    ]
    assert sum(len(t) for t in texts) < 2000
    assert detect_language_from_texts(texts) == "en"
    assert detect_language_from_texts(["hi"]) is None
    assert detect_language_from_texts([]) is None
