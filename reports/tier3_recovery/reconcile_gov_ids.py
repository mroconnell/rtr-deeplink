"""Second pass at government identity, using only real evidence already
captured in resolved_257.jsonl (the page's own extracted jurisdiction
text) -- no new network calls, no invented names.

Two honest retries for rows the ladder didn't resolve on the first pass:
1. Full state name -> 2-letter abbreviation (e.g. "Kane County Hospital,
   Utah" -> "Kane County Hospital, UT") -- a format fix, not a guess.
2. A jurisdiction name the page itself gave us, on a host the ladder
   won't trust without a per-video pin (MULTI_GOV_HOSTS) -- retried with
   tenant_host=None so the name-only rungs get a chance. If that resolves
   cleanly, the government note says so explicitly and flags that a real
   tenant_overrides.csv pin should be added for this to be trusted
   automatically in the future.

Never invents a name from a hostname or file path -- only reuses text the
adapter already extracted from the real page.
"""
import os
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import sys
import json
from pathlib import Path

sys.path.insert(0, ".")
from app.utils.gov_registry.resolver import resolve_government, _tenant_host
from urllib.parse import urlparse

REPORTS = Path("reports/tier3_recovery")
IN_PATH = REPORTS / "resolved_257.jsonl"
OUT_PATH = REPORTS / "resolved_257_reconciled.jsonl"

STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}


def normalize_state_suffix(name: str) -> str | None:
    if "," not in name:
        return None
    prefix, _, suffix = name.rpartition(",")
    suffix_clean = suffix.strip().lower()
    abbr = STATE_NAME_TO_ABBR.get(suffix_clean)
    if abbr:
        return f"{prefix.strip()}, {abbr}"
    return None


def reconcile(row: dict) -> dict:
    if row.get("gov_id"):
        row["gov_resolution_note"] = "resolved on first pass"
        return row

    name = row.get("jurisdiction_name")
    if not name:
        row["gov_resolution_note"] = "no jurisdiction text extracted from the page -- TBD"
        return row

    host = urlparse(row["url"]).netloc
    tenant_host = _tenant_host(host)
    path = urlparse(row["url"]).path

    # retry 1: full state name -> abbreviation, same tenant_host as before
    normalized = normalize_state_suffix(name)
    if normalized:
        m = resolve_government(normalized, tenant_host=tenant_host, path=path)
        if m.tier in ("registry", "pinned"):
            row["gov_id"] = m.gov_id
            row["gov_confidence"] = m.tier
            row["gov_evidence"] = m.evidence
            row["gov_resolution_note"] = (
                f"resolved after normalizing the page's own state name "
                f"('{name}' -> '{normalized}')"
            )
            return row

    # retry 2: bare name-only lookup (bypasses a MULTI_GOV_HOSTS block),
    # using both the original name and the state-normalized one
    for candidate in filter(None, [normalized, name]):
        m = resolve_government(candidate, tenant_host=None, path=None)
        if m.tier in ("registry", "pinned"):
            row["gov_id"] = m.gov_id
            row["gov_confidence"] = m.tier
            row["gov_evidence"] = m.evidence
            row["gov_resolution_note"] = (
                f"resolved from the page's own text ('{name}'), but {tenant_host} "
                f"is a shared multi-government host with no per-video pin -- "
                f"add a tenant_overrides.csv row before trusting this "
                f"automatically in a future ingest"
            )
            return row

    row["gov_resolution_note"] = (
        f"page named '{name}' but no confident registry match was found -- "
        f"TBD (possibly a special district not yet in the registry, or an "
        f"ambiguous/misspelled name)"
    )
    return row


def main():
    rows = [json.loads(l) for l in IN_PATH.read_text().splitlines()]
    reconciled = [reconcile(r) for r in rows]
    with open(OUT_PATH, "w") as f:
        for r in reconciled:
            f.write(json.dumps(r) + "\n")

    from collections import Counter
    print("total:", len(reconciled))
    print(Counter(r["gov_confidence"] for r in reconciled))
    newly_resolved = [r for r in reconciled if r["gov_id"] and "resolved after" in r.get("gov_resolution_note", "") or "resolved from the page" in r.get("gov_resolution_note", "")]
    print("newly resolved by this reconciliation pass:", len(newly_resolved))


if __name__ == "__main__":
    main()
