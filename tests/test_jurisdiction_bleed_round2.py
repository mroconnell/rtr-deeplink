"""Regression tests for the 2026-08-18 jurisdiction-bleed fixes (third
pass) -- 4 new patterns found live on `/coverage`, all confirmed distinct
root causes from the 2026-08-17 fixes (see BACKLOG_DONE.md's "jurisdiction-
bleed, third pass" entry for full investigation detail):

  Fix 1: eScribe's subdomain-derived jurisdiction fallback
         (`EscribeAssetFinder._jurisdiction_from_subdomain()`) now
         delegates to the shared, Census/StatsCan-table-gated
         `jurisdiction_enrich.validated_label_extract()` instead of a
         bare, ungated wordninja split.
  Fix 2: leading-date bleed, stripped as a `finalize_jurisdiction()`
         preprocessing step (`_LEADING_DATE_RE`).
  Fix 3: glued file-extension bleed, space-inserted as a
         `finalize_jurisdiction()` preprocessing step
         (`_GLUED_EXTENSION_RE`).
  Fix 4: a closed, curated stoplist of confirmed single trailing junk
         words (`_KNOWN_JUNK_TAIL_WORDS`) in `_looks_like_bleed()`.

Every raw string below is a real value found live on `/coverage`,
2026-08-18 -- not synthetic/invented, same convention as the 2026-08-17
bleed test suite (tests/test_jurisdiction_enrich.py).
"""

from app.platforms.escribe import EscribeAssetFinder
from app.utils import jurisdiction_enrich as je


# --- Fix 1: eScribe subdomain extraction, now gated ---


def test_escribe_subdomain_fix1_resolves_real_examples():
    # Real production subdomains (pub-{label}.escribemeetings.com) --
    # confirmed via /internal/pages/all-urls, 2026-08-18. Each of these
    # validates against places.csv/counties.csv once the subdomain label
    # is correctly reconstructed.
    cases = [
        ("townofbonnyville", "Bonnyville"),  # AB -- needs the glued-
        # rejoin tier: wordninja splits this to town/of/bonny/ville, and
        # only the REJOINED-WITHOUT-SPACES form ("Bonnyville") validates;
        # the spaced form ("Bonny Ville") does not.
        ("townofgrandvalley", "Grand Valley"),  # ON -- needs only the
        # spaced-join tier (wordninja splits this cleanly).
        ("pointedward", "Point Edward"),  # ON
        ("bouldercounty", "Boulder County"),  # CO
        ("beaumontab", "Beaumont"),  # AB -- needs the Canadian
        # province-code trailing-strip (added this pass; the shared
        # trailing-abbreviation strip was previously US-state-only).
        ("mackenziebc", "Mackenzie"),  # BC -- same province-code need.
    ]
    for label, expected in cases:
        got = EscribeAssetFinder._jurisdiction_from_subdomain(
            f"https://pub-{label}.escribemeetings.com/x"
        )
        assert got == expected, f"{label!r}: expected {expected!r}, got {got!r}"


def test_escribe_subdomain_fix1_honestly_declines_when_wordninja_cant_split_it():
    # "townofws": wordninja can't meaningfully split "ws" (too short/
    # ambiguous) -- explicitly flagged in the original ask as expected to
    # stay unresolved without a second real example to ground a guess in.
    assert (
        EscribeAssetFinder._jurisdiction_from_subdomain(
            "https://pub-townofws.escribemeetings.com/x"
        )
        is None
    )
    # "bradfordwestgwillimbury": real ON municipality (3 words), but
    # wordninja mis-splits it into garbage (bradford/west/g/will/im/bury)
    # that never reassembles into anything table-valid -- declining here
    # (rather than the old code's confident "Bradford West G Will Im
    # Bury") is the correct, safer outcome even though it doesn't resolve
    # the name. See BACKLOG.md's StatsCan table-completeness entry.
    assert (
        EscribeAssetFinder._jurisdiction_from_subdomain(
            "https://pub-bradfordwestgwillimbury.escribemeetings.com/x"
        )
        is None
    )


def test_validated_label_extract_spaced_before_glued_avoids_wrong_coincidental_match():
    # Real regression this ordering specifically guards against, found by
    # sweeping every real Granicus subdomain in production before
    # shipping: trying the GLUED-rejoin tier before the SPACED tier wrongly
    # turns "cityofnorthport" into "Northport" (a real but WRONG place --
    # a coincidental table match) instead of the correct spaced "North
    # Port". Spaced must be tried first.
    assert je.validated_label_extract("cityofnorthport") == "North Port"
    assert je.validated_label_extract("oakridgetn") == "Oak Ridge"


def test_validated_label_extract_rejects_single_letter_leftover_word():
    # Real data artifact found adding the province-code list this pass:
    # "citynmb" wordninja-splits to ['city','n','mb'] -- stripping the
    # leading "city" and the trailing province code "mb" leaves the sole
    # word "n", which was found to validate against a single-letter row
    # in places.csv (almost certainly a data artifact, not a real place).
    # No real municipality is meaningfully 1-2 letters, so this must
    # decline rather than return "N".
    assert je.validated_label_extract("citynmb") is None


# --- Fix 2: leading-date bleed ---


def test_finalize_jurisdiction_strips_leading_date_bleed():
    # Real raw values, Bellefonte/State College Borough, PA -- found live
    # on /coverage, 2026-08-18.
    result = je.finalize_jurisdiction("6/16/25 Bellefonte Borough")
    assert result.jurisdiction == "Bellefonte Borough"
    assert result.confidence == "validated"

    result = je.finalize_jurisdiction("7/1/24 Bellefonte Borough")
    assert result.jurisdiction == "Bellefonte Borough"
    assert result.confidence == "validated"

    result = je.finalize_jurisdiction("8/6/25 State College Borough")
    assert result.jurisdiction == "State College Borough"
    assert result.confidence == "validated"


def test_finalize_jurisdiction_leading_date_strip_never_empties_a_date_only_string():
    # Guard case: stripping a leading date must never collapse the value
    # to nothing -- a bare date with no real jurisdiction left over keeps
    # the original text (still "unverified", but not silently blanked).
    result = je.finalize_jurisdiction("6/16/25")
    assert result.jurisdiction == "6/16/25"
    assert result.confidence == "unverified"


# --- Fix 3: glued file-extension bleed ---


def test_finalize_jurisdiction_strips_glued_file_extension_bleed():
    # Real raw value, Brock Township, ON -- an eScribe/CivicWeb agenda
    # page listing an attachment filename inline with no space before the
    # extension. Found live on /coverage, 2026-08-18; previously tracked
    # as an open gap in BACKLOG.md ("Brock Township... glued directly to
    # a filename"), now closed.
    raw = (
        "Township of Brock.pdf Pulled from Council Information Index "
        "by Regional Councillor Pettingill Rescue Lake Simcoe Coalition "
        "Communication Number"
    )
    result = je.finalize_jurisdiction(raw)
    assert result.jurisdiction == "Township of Brock"
    assert result.confidence == "repaired"


def test_finalize_jurisdiction_rochestercitymn_repairs_to_rochester_mn():
    # This used to assert "stays unverified": the fix was deliberately
    # deferred while only ONE glued-title IQM2 customer was known (see
    # the old BACKLOG.md "RochestercityMN root-caused" entry, which
    # predicted the fix becomes buildable the moment a second example
    # appears). The 2026-08-23 data-quality pass found five more real
    # IQM2 tenants with title-as-branding garbage ("MaderaCounty, CA",
    # "Arcata City, CA", "Redding City, California", "Ringgold City, GA",
    # "Healdsburg City, CA" -- all confirmed live in each tenant's own
    # <title> tag), so finalize_jurisdiction() now runs a glued-label
    # repair (the same Census-validated extractor the subdomain paths
    # trust) plus a branding "X City" strip.
    result = je.finalize_jurisdiction("RochestercityMN")
    assert result.jurisdiction == "Rochester, MN"
    assert result.confidence == "repaired"
