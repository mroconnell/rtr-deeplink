"""robots.txt Allow and Disallow rules, read the way RFC 9309 says (Ryan, 2026-10-02:
honor any matching Disallow, in both repos, as one rule).

This is the same matcher as rtr-findmeeting's `findmeeting/robotsrules.py`, ported so that
the two repos read a robots.txt identically. Pure: no network, no clock, no files. If you
change a rule here, change it there too.

The rules, in plain words
1. Which group applies. A robots.txt is a list of groups. Each group names one or more bots
   (User-agent lines) and then lists rules. The group that names our product token
   (`rtr-upcoming`) applies. If no group names us, the `*` group applies. Several groups for
   the same bot are joined into one. If neither exists there are no rules, so everything is
   allowed.
2. Which rule wins. A path matches a rule when the rule's pattern is the start of the path.
   Of all the rules that match, the LONGEST pattern wins. If an Allow and a Disallow match
   with the same length, Allow wins. No rule matches: allowed.
3. Patterns. `*` stands for any run of characters. A `$` at the very end means "the path ends
   here". Matching is on the path plus the query (`/a/b?x=1`), is case-sensitive, and ignores
   spelling differences in percent-encoding (`%7e` and `~` are the same).
4. An empty `Disallow:` allows everything. An empty `Allow:` does nothing.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, NamedTuple, Optional
from urllib.parse import urlsplit

PRODUCT_TOKEN = "rtr-upcoming"


class Rule(NamedTuple):
    allow: bool
    pattern: str  # as written, never empty


_UNRESERVED = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_HEX2 = re.compile(rb"[0-9A-Fa-f]{2}")


def normalize(text: str) -> str:
    """Percent-encoding made comparable: an escaped unreserved letter, digit or `-._~` is
    decoded; every other escape keeps its place with upper-case hex; a space, a control
    character or a non-ASCII character is escaped (as UTF-8). Reserved characters
    (`/ ? & = * $`) written plainly stay plain."""
    b = text.encode("utf-8")
    out: list[str] = []
    i, n = 0, len(b)
    while i < n:
        c = b[i]
        if c == 0x25 and i + 2 < n and _HEX2.fullmatch(b[i + 1 : i + 3]):
            v = int(b[i + 1 : i + 3], 16)
            out.append(chr(v) if v in _UNRESERVED else "%%%02X" % v)
            i += 3
            continue
        out.append("%%%02X" % c if (c <= 0x20 or c >= 0x7F) else chr(c))
        i += 1
    return "".join(out)


def path_and_query(url_or_path: str) -> str:
    """`/a/b?x=1` from an address (or from a path that is already one). No fragment. An
    empty path is `/`."""
    s = (url_or_path or "").strip()
    if "://" in s or s.startswith("//"):
        p = urlsplit(s)
        path, query = p.path or "/", p.query
    else:
        s = s.split("#", 1)[0]
        path, _, query = s.partition("?")
        path = path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return path + ("?" + query if query else "")


@lru_cache(maxsize=4096)
def _compile(pattern: str) -> tuple[re.Pattern, int]:
    p = normalize(pattern)
    anchored = p.endswith("$")
    body = p[:-1] if anchored else p
    rx = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile("^" + rx + (r"\Z" if anchored else ""), re.S), len(p)


def parse_rules(text: str, token: str = PRODUCT_TOKEN) -> list[Rule]:
    """The Allow and Disallow rules that apply to us, from a robots.txt text (rule 1). An
    empty Disallow adds no rule."""
    groups: list[tuple[list[str], list[Rule]]] = []
    agents: list[str] = []
    rules: list[Rule] = []
    in_agents = False
    started = False
    # A UTF-8 byte order mark (documents-on-demand.com tenants serve one) would glue itself
    # to the first field name ("\ufeffuser-agent"), leave no group, and read as allow-all.
    # Strip it from the text start and from each line.
    for raw in (text or "").lstrip("\ufeff").splitlines():
        line = raw.replace("\ufeff", "", 1) if raw.startswith("\ufeff") else raw
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if not in_agents:
                if started:
                    groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
            in_agents, started = True, True
        elif key in ("allow", "disallow"):
            in_agents = False
            if started and value:
                rules.append(Rule(key == "allow", value))
        else:
            in_agents = False
    if started:
        groups.append((agents, rules))

    def names_us(a: str) -> bool:
        return a == token or a.split("/")[0] == token

    ours = [g for g in groups if any(names_us(a) for a in g[0])]
    chosen = ours or [g for g in groups if "*" in g[0]]
    return [r for _, rs in chosen for r in rs]


def matching_rule(
    rules: Optional[Iterable[Rule]], url_or_path: str
) -> tuple[bool, Optional[Rule]]:
    """(allowed, the rule that decided it). `(True, None)` when no rule matches."""
    target = normalize(path_and_query(url_or_path))
    best_len, best_rule = -1, None
    for r in rules or ():
        rx, length = _compile(r[1])
        if rx.match(target) and (
            length > best_len or (length == best_len and bool(r[0]))
        ):
            best_len, best_rule = length, r
    if best_rule is None:
        return True, None
    return bool(best_rule[0]), best_rule


def is_allowed(rules: Optional[Iterable[Rule]], url_or_path: str) -> bool:
    """May we request this path (with its query)? `rules` is the list `parse_rules` gives
    (None or empty: yes)."""
    return matching_rule(rules, url_or_path)[0]
