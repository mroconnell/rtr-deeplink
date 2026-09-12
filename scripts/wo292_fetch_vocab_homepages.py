#!/usr/bin/env python3
"""WO-292 step 0: fetch the school-district homepages that carry the
step-0 vocabulary-measurement positives once (417 districts already
known, via jurisdiction_coverage.csv's suspected_video_provider, to run
a YouTube or Vimeo channel, plus the 6 us:sd: districts with an existing
Archive page), saving every outbound link (href, anchor text, position)
as JSON-lines so scripts/wo292_derive_school_hop_weights.py can build
the school hop-link vocabulary offline without a second fetch.
Resumable by domain.

Reuses scripts/wo282_recon.py's fetch_homepage()/extract_links() and
scripts/wo273_recon.py's DNS/rate-limit/politeness helpers verbatim --
no new fetch logic. Adds the 2026-09-12 Akamai/govAccess CNAME gate
(this repo's own preamble rule for that morning's incident): a domain
whose apex or www CNAMEs to granicusgovaccess.net is skipped and
recorded blocked-waf-akamai rather than retried, per that confirmed
IP-level WAF block.

Politeness: one government (domain) at a time in this script (no
concurrency -- this is the small step-0 measurement fetch, not the
1,000-district phase 1 pilot itself), >=1.5s between governments on top
of wo273_recon's own >=2.5s-per-host floor inside fetch_homepage itself.
Honest User-Agent (w273.HEADERS). Never past a human-verification gate
(fetch_homepage's own is_challenge() check already stops there).

Run (from the repo root, shared venv):
    .venv/bin/python scripts/wo292_fetch_vocab_homepages.py \\
        <targets.csv> <out.jsonl> [limit]

`targets.csv` needs `gov_id,domain` columns (see
scripts/wo292_build_population.py's sibling target-list step, or build
one directly from jurisdiction_coverage.csv's us:sd: rows with
suspected_video_provider in {youtube, vimeo} or transcribed=true).
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import wo273_recon as w273  # noqa: E402
import wo282_recon as w282  # noqa: E402

# Redirect wo282_recon's homepage-gz save dir to THIS run's own scratch
# dir (not wo282's own agent-scoped default) -- override via env var so
# a subagent honors its own private scratch directory (WO-200's rule:
# every session shares the same scratchpad root, so a bare/default path
# risks colliding with another WO's files).
w282.SCRATCH_DIR = Path(
    os.environ.get(
        "WO292_HOMEPAGE_SCRATCH_DIR",
        str(REPO_ROOT / "scripts" / "_wo292_scratch" / "homepages"),
    )
)

AKAMAI_GOVACCESS_CNAME = "granicusgovaccess.net"
BETWEEN_GOV_SLEEP = 1.5


def load_targets(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_done(out_path):
    done = set()
    p = Path(out_path)
    if p.exists():
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                done.add(rec.get("domain"))
    return done


def main():
    targets_path = sys.argv[1]
    out_path = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    targets = load_targets(targets_path)
    by_domain = {}
    for t in targets:
        d = t["domain"].strip()
        if d and d not in by_domain:
            by_domain[d] = t
    domains = list(by_domain.keys())

    done = load_done(out_path)
    print(f"{len(domains)} unique domains, {len(done)} already done", file=sys.stderr)

    remaining = [d for d in domains if d not in done]
    if limit:
        remaining = remaining[:limit]

    n = 0
    with open(out_path, "a") as out_f:
        for domain in remaining:
            n += 1
            rec = {"domain": domain, "gov_id": by_domain[domain].get("gov_id", "")}
            apex_cname = (w273.dig("CNAME", domain) or [""])[0]
            www_cname = (w273.dig("CNAME", f"www.{domain}") or [""])[0]
            apex_a = w273.dig("A", domain)
            www_a = w273.dig("A", f"www.{domain}")
            rec["apex_cname"] = apex_cname
            rec["www_cname"] = www_cname

            if (
                AKAMAI_GOVACCESS_CNAME in apex_cname
                or AKAMAI_GOVACCESS_CNAME in www_cname
            ):
                rec["outcome"] = "blocked-waf-akamai"
                rec["evidence"] = apex_cname or www_cname
                out_f.write(json.dumps(rec) + "\n")
                out_f.flush()
                print(
                    f"[{n}/{len(remaining)}] {domain}: blocked-waf-akamai ({rec['evidence']})",
                    file=sys.stderr,
                )
                time.sleep(BETWEEN_GOV_SLEEP)
                continue

            if not (apex_a or apex_cname or www_a or www_cname):
                rec["outcome"] = "dns-unresolvable"
                out_f.write(json.dumps(rec) + "\n")
                out_f.flush()
                print(
                    f"[{n}/{len(remaining)}] {domain}: dns-unresolvable",
                    file=sys.stderr,
                )
                time.sleep(BETWEEN_GOV_SLEEP)
                continue

            hp = w282.fetch_homepage(domain)
            rec["outcome"] = (
                "fetched" if hp["fetched"] else hp["access_mode"] or "error"
            )
            rec["status"] = hp["status"]
            rec["final_url"] = hp["final_url"]
            rec["access_mode"] = hp["access_mode"]
            rec["link_count"] = hp["link_count"]
            rec["links"] = hp["links"]
            rec["error"] = hp["error"]
            out_f.write(json.dumps(rec) + "\n")
            out_f.flush()
            print(
                f"[{n}/{len(remaining)}] {domain}: {rec['outcome']} "
                f"(status={hp['status']}, links={hp['link_count']})",
                file=sys.stderr,
            )
            time.sleep(BETWEEN_GOV_SLEEP)

    print(f"done. wrote to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
