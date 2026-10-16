"""The Census/StatCan source decode in both data generators (backlog
triage 2026-10-16).

Synthetic bytes, real names: La Cañada Flintridge's Gazetteer row was
UTF-8 in the source and came out "La CaÃ±ada Flintridge" under the old
blanket latin-1 decode (fixed by hand in PR #855). The latin-1 line uses
a real Puerto Rico municipio name. The generators' real source files are
not in the repo, so this checks the decode rule itself.
"""

import pytest

from scripts import build_gov_registry_data, build_jurisdiction_data

UTF8_LINE = "0639003\tLa Cañada Flintridge city\n".encode("utf-8")
LATIN1_LINE = "72021\tBayamón Municipio\n".encode("latin-1")


@pytest.mark.parametrize(
    "decode",
    [
        build_jurisdiction_data._decode_census_bytes,
        build_gov_registry_data._decode_census_bytes,
    ],
)
def test_each_line_decodes_as_what_it_really_is(decode):
    text = decode(b"GEOID\tNAME\n" + UTF8_LINE + LATIN1_LINE)
    assert "La Cañada Flintridge city" in text
    assert "Bayamón Municipio" in text
    assert "Ã" not in text
    assert decode(b"\xef\xbb\xbfGEOID\n").startswith("GEOID")
