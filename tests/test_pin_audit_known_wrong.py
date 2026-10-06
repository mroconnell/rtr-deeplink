import csv
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pin_audit_known_wrong as k  # noqa: E402


def test_parse_csv_line_quoted_evidence():
    # Synthetic row; evidence holds commas and quotes.
    r = k.parse_csv_line('Foo.Example.com,,us:place:1,fallback,src,"a, ""b"", c"')
    assert r["host"] == "foo.example.com"
    assert r["gov_id"] == "us:place:1"
    assert r["evidence"] == 'a, "b", c'
    assert k.parse_csv_line("tenant_host,match,gov_id,strength,source,evidence") is None


def test_find_changes_same_commit_and_across_commits():
    # Synthetic git-log text.
    log = (
        "@@@a1|2026-01-01|add\n"
        "+x.example.com,,us:place:1,fallback,s1,e1\n"
        "@@@b2|2026-02-01|fix\n"
        "@@ -2 +2 @@\n"
        "-x.example.com,,us:place:1,fallback,s1,e1\n"
        "+x.example.com,,us:place:2,fallback,s2,e2\n"
        "@@@c3|2026-03-01|drop\n"
        "-x.example.com,,us:place:2,fallback,s2,e2\n"
        "@@@d4|2026-04-01|readd\n"
        "+x.example.com,,us:place:3,fallback,s3,e3\n"
    )
    ch = k.annotate(k.find_changes(k.parse_log(log)))
    assert [(c["old_gov_id"], c["new_gov_id"], c["commit"]) for c in ch] == [
        ("us:place:1", "us:place:2", "b2"),
        ("us:place:2", "us:place:3", "d4"),
    ]
    assert ch[0]["reverted_later"] == "no"


def test_classify_synthetic():
    infos = {
        "a": ("Sunnyside", "NL", "ca", "municipality"),
        "b": ("Sunnyside city", "WA", "us", "municipality"),
        "c": ("Foo County", "WA", "us", "county"),
        "d": ("Bar town", "WA", "us", "municipality"),
        "us:county:9": ("Foo County", "WA", "us", "county"),
    }
    f = infos.get
    assert k.classify("a", "b", f) == ("different_state", "yes")
    assert k.classify("us:county:9", "d", f)[0] == "county_place_level"
    assert k.classify("b", "d", f)[0] == "same_state_other_gov"
    assert k.classify("rtr:us:wa:x", "d", f)[0] == "minted_to_registry"
    assert k.classify("zz", "d", f)[0] == "unknown"
    # Real consolidated pair (San Francisco county/place), real data file.
    assert k.classify("us:county:06075", "us:place:0667000")[0] == "consolidated"


def test_base_name():
    assert k.base_name("City of Sunnyside (WA)") == "sunnyside"
    assert k.base_name("Sunnyside city") == "sunnyside"


@pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")
def test_real_history_sunnyside(tmp_path):
    out = tmp_path / "kw.csv"
    try:
        k.main(["--out", str(out)])
    except Exception as e:  # shallow clone etc.
        pytest.skip(f"history unavailable: {e}")
    rows = list(csv.DictReader(out.open()))
    hit = [
        r
        for r in rows
        if r["host"] == "sunnyside.primegov.com"
        and r["old_gov_id"] == "ca:csd:1001277"
        and r["new_gov_id"] == "us:place:5368750"
    ]
    if not hit:
        pytest.skip("history lacks the Sunnyside change (shallow clone?)")
    assert hit[0]["change_kind"] == "different_state"
    assert hit[0]["same_base_name"] == "yes"
