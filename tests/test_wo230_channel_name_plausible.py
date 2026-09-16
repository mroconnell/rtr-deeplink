"""WO-254: `channel_name_plausible()`'s word-tokenizer rejected a real
own-channel when the handle ran the government's name together with no
spaces (found during WO-249, `BACKLOG.md`). South River borough, NJ's
own real municipal channel, confirmed live via YouTube's oEmbed to be
"South River NJ TV35", has the handle `@southrivernjtv3564` -- that
tokenizes as one unbroken blob under the plain `[a-z]+` splitter, so the
old exact-token-set check could never match it, no matter whose channel
it really was.

These tests use real handle shapes: South River borough, NJ is the
confirmed backlog case; the Atoka County/City of Atoka and Niles city,
MI/Berrien County pairs are real, confirmed government-name collisions
in this repo's own jurisdiction data
(`app/utils/jurisdiction_data/counties.csv`, `.../places.csv`) and in
`BACKLOG_DONE.md`'s WO-247 entry; Rockingham County, VA's real tourism
channel (`@VisitRockinghamVA`, also from WO-247's own sweep) is the
concrete counterexample that rules out a bare single-word substring
match."""

from scripts.wo230_agendacenter_followup import (
    channel_name_plausible,
    _run_together_name_match,
)


# --- The confirmed real fix: a compound handle with no separators -----


def test_south_river_nj_compound_handle_matches_its_own_government():
    # Real handle (with the leading "@" already stripped, matching how
    # channel_text is built in wo230_agendacenter_followup.py).
    assert channel_name_plausible("southrivernjtv3564", "South River borough, NJ")


def test_west_fargo_style_compound_handle_matches_two_real_words():
    assert channel_name_plausible("cityofwestfargo8572", "West Fargo city, ND")


def test_single_word_government_matches_only_when_anchored_to_a_real_gov_prefix():
    # "Weston" alone is one real word -- only accepted when it's run
    # together with a genuine "town of"/"city of"-style prefix, the real
    # shape a municipal handle takes.
    assert channel_name_plausible("townofwestonmaofficial", "Weston town, MA")


# --- Existing negative cases that must stay negative -------------------


def test_unrelated_channel_with_no_shared_word_stays_implausible():
    # Already-documented existing negative (channel_name_plausible's own
    # docstring): a real, unrelated channel shares no word at all.
    assert not channel_name_plausible("Union County OH", "Shelby County, OH")


def test_rockingham_tourism_channel_stays_implausible():
    # WO-247's own real find: Rockingham County, VA's "Visit
    # RockinghamVA" tourism/promotion channel, not the county's own
    # government channel -- this is the exact counterexample that rules
    # out a bare single-word substring match (both are one run-together
    # blob that legitimately contains "rockingham"), so this must NOT
    # match even with the new compound-handle fallback in place.
    assert not channel_name_plausible("visitrockinghamva", "Rockingham County, VA")


def test_atoka_county_and_city_of_atoka_share_a_word_same_as_before():
    # Atoka County, OK and Atoka city, OK are two real, distinct
    # governments in this repo's own jurisdiction data
    # (app/utils/jurisdiction_data/counties.csv, places.csv) that share
    # the word "atoka". channel_name_plausible is documented as a weak,
    # non-definitive signal (its own docstring) -- it already returned
    # True for this pair via the plain exact-token-set check before this
    # WO (both tokenize to a shared "atoka" token), and still does. This
    # test exists to record that the WO-254 fallback doesn't change that
    # pre-existing behavior one way or the other -- disambiguating the
    # two real Atoka governments is the hand-check/jurisdiction-match
    # layer's job, not this function's.
    assert channel_name_plausible("City of Atoka", "Atoka County, OK")


def test_niles_city_mi_does_not_match_berrien_countys_own_channel():
    # Real WO-247 find: Niles city, MI's search turned up Berrien
    # County, MI's own channel (a different real government -- "Kind A,
    # owner elsewhere" in that WO's own report). The two names share no
    # word at all, so this must stay implausible under both the old
    # exact-token check and the new compound-handle fallback.
    assert not channel_name_plausible("Berrien County Michigan", "Niles city, MI")
    assert not channel_name_plausible("berriencountymi", "Niles city, MI")


def test_bare_run_together_match_requires_at_least_two_words_or_an_anchor():
    # Internal unit check on the fallback itself: a single real word
    # with no generic-prefix anchor at all must not match, even though it
    # appears as a plain substring -- this is the exact shape the
    # Rockingham test above guards against, asserted directly against
    # the helper so a future edit that removes the anchor requirement
    # fails here first.
    assert not _run_together_name_match("Rockingham County, VA", "visitrockinghamva")
    assert _run_together_name_match("Weston town, MA", "townofwestonmaofficial")
    assert _run_together_name_match("South River borough, NJ", "southrivernjtv3564")
