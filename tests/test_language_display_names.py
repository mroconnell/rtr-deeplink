"""The Archive's version picker names every language the detector can return.

WO-1164 (2026-09-29): real TelVue pages showed Arabic and Farsi caption
versions as bare "ar"/"fa" in the dropdown, because the name table held only
English and Spanish. This checks the table against langdetect's own bundled
profile list -- the full set of codes detect_language_from_texts() can
return -- so a gap can't reopen silently.
"""

import os

import langdetect

from archive.utils.language import LANGUAGE_DISPLAY_NAMES, language_display_name


def _langdetect_codes():
    profiles = os.path.join(os.path.dirname(langdetect.__file__), "profiles")
    return sorted(os.listdir(profiles))


def test_every_detectable_language_has_a_name():
    codes = _langdetect_codes()
    assert codes, "langdetect profile list came back empty"
    missing = [c for c in codes if c not in LANGUAGE_DISPLAY_NAMES]
    assert missing == []


def test_names_are_not_the_bare_code():
    for code, name in LANGUAGE_DISPLAY_NAMES.items():
        assert name and name != code


def test_arabic_and_farsi_show_names():
    assert language_display_name("ar") == "العربية"
    assert language_display_name("fa") == "فارسی"


def test_existing_names_and_fallbacks_unchanged():
    assert language_display_name("en") == "English"
    assert language_display_name("es") == "Español"
    assert language_display_name(None) == "unknown"
    assert language_display_name("xx") == "xx"
