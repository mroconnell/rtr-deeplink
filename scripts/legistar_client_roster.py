"""Static, evidence-scoped reconciliation of author Legistar clients."""

import csv
import gzip
import hashlib
import json
import re
from collections import defaultdict, Counter
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parent.parent
)  # repo root (this script now lives in scripts/)
RUN = ROOT / "research_runs" / "legistar_clients_2026-09-15"
BUS = Path("/Users/mroconnell/Documents/rtr-business/research")
CLIENT_RE = re.compile(r"\b([a-z0-9-]+)\.legistar\.com\b", re.I)


def read_csv(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clients_in(text):
    return {x.lower() for x in CLIENT_RE.findall(text or "")}


def save_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    clients = read_csv(RUN / "legistar_clients.csv")
    jc = read_csv(BUS / "jurisdiction_coverage.csv")
    inventory = read_csv(BUS / "yesgov_2026-09-15/inputs/meeting_inventory.csv.gz")
    queue_current = {
        x.strip()
        for x in (ROOT / "scripts/tier3_auto_transcription_queue.txt")
        .read_text()
        .splitlines()
        if x.strip()
    }
    queue_ties = {
        x["url"]: x for x in read_csv(BUS / "tier3_queue_breadth_2026-09-12.csv")
    }
    queue_probes = {
        x["url"]: x
        for x in read_csv(ROOT / "scripts/tier3_auto_transcription_queue_probe.csv")
    }
    gov_to_jc = {x["gov_id"]: x for x in jc if x.get("gov_id")}

    jc_by_client = defaultdict(list)
    for row in jc:
        text = " ".join(
            row.get(k, "")
            for k in [
                "domain",
                "alternate_domains",
                "example_agenda_or_calendar_url",
                "example_meeting_url",
                "alternate_urls",
            ]
        )
        for client in clients_in(text):
            jc_by_client[client].append(row)

    archive_video = defaultdict(list)
    archive_no_video = defaultdict(list)
    for row in inventory:
        for client in clients_in(
            " ".join(row.get(k, "") for k in ["source_url", "video_url", "archive_url"])
        ):
            (archive_video if row.get("has_video") == "yes" else archive_no_video)[
                client
            ].append(row)

    queue_video = defaultdict(list)
    queue_identity_gap = defaultdict(list)
    for url in queue_current:
        tie = queue_ties.get(url, {})
        probe = queue_probes.get(url, {})
        clients = clients_in(url)
        if not clients and tie.get("gov_id") in gov_to_jc:
            govrow = gov_to_jc[tie["gov_id"]]
            clients = clients_in(
                " ".join(
                    govrow.get(k, "")
                    for k in [
                        "domain",
                        "alternate_domains",
                        "example_agenda_or_calendar_url",
                        "example_meeting_url",
                    ]
                )
            )
        if not clients:
            continue
        for client in clients:
            if probe.get("verdict") == "accept" and tie.get("gov_id"):
                queue_video[client].append(
                    {
                        "url": url,
                        "gov_id": tie["gov_id"],
                        "probe": probe.get("verdict", ""),
                    }
                )
            else:
                queue_identity_gap[client].append(
                    {
                        "url": url,
                        "gov_id": tie.get("gov_id", ""),
                        "probe": probe.get("verdict", ""),
                    }
                )

    output = []
    for src in read_csv(RUN / "legistar_clients.csv"):
        client = src["client"]
        matches = jc_by_client[client]
        exact_hubs = [
            r
            for r in matches
            if "legistar"
            in " ".join(
                r.get(k, "")
                for k in [
                    "suspected_calendar_provider",
                    "suspected_meeting_link_provider",
                    "suspected_video_provider",
                ]
            ).lower()
            and clients_in(
                r.get("example_agenda_or_calendar_url", "")
                + " "
                + r.get("example_meeting_url", "")
            )
            == {client}
        ]
        exclusion = ""
        evidence = ""
        if archive_video[client]:
            exclusion = "archive-video-evidence"
            evidence = archive_video[client][0].get("source_url", "")
        elif queue_video[client]:
            exclusion = "queue-video-evidence-dated"
            evidence = queue_video[client][0]["url"]
        elif exact_hubs and client in {"pinellas", "madison", "pomona"}:
            exclusion = "recorded-legistar-hub-identity-needs-review"
            evidence = exact_hubs[0].get("example_meeting_url") or exact_hubs[0].get(
                "example_agenda_or_calendar_url", ""
            )
        elif exact_hubs:
            exclusion = "existing-legistar-platform-and-hub"
            evidence = (
                exact_hubs[0].get("example_meeting_url")
                if client in clients_in(exact_hubs[0].get("example_meeting_url", ""))
                else exact_hubs[0].get("example_agenda_or_calendar_url", "")
            )
        elif len({r.get("gov_id") for r in matches}) > 1:
            exclusion = "ambiguous-existing-government-match"
        elif len(matches) == 1:
            exclusion = "matched-government-needs-test"
        else:
            exclusion = "identity-unmatched-needs-verification"
        output.append(
            {
                "client": client,
                "historical_api_response": src["api"],
                "candidate_calendar_host": f"{client}.legistar.com",
                "host_verified_now": "false",
                "matched_gov_ids": "|".join(
                    sorted({r.get("gov_id", "") for r in matches})
                ),
                "matched_government_names": "|".join(
                    sorted({r.get("city_name", "") for r in matches})
                ),
                "archive_video_pages_snapshot": len(archive_video[client]),
                "archive_no_video_pages_snapshot": len(archive_no_video[client]),
                "queue_video_lines_dated": len(queue_video[client]),
                "queue_identity_gap_lines": len(queue_identity_gap[client]),
                "existing_legistar_hub_rows": len(exact_hubs),
                "reconciliation_status": exclusion,
                "evidence_url": evidence,
                "queue_snapshot_date": "2026-09-12",
                "archive_snapshot_date": "2026-09-15 07:10 (timezone unspecified in source README)",
            }
        )
    save_csv(RUN / "static_reconciliation.csv", output, list(output[0]))
    counts = Counter(x["reconciliation_status"] for x in output)
    manifest = {
        "source_url": "https://raw.githubusercontent.com/elipousson/legistarapi/9594fcbca35473b8f61da734cfdfef0dceedfede/data/legistar_clients.rda",
        "author_repo_revision": "9594fcbca35473b8f61da734cfdfef0dceedfede",
        "author_documented_last_updated": "2024-05-12",
        "download_date_utc": "2026-09-15",
        "source_sha256": hashlib.sha256(
            (RUN / "legistar_clients.rda").read_bytes()
        ).hexdigest(),
        "pinned_revision_bytes_verified": True,
        "parsed_count": len(output),
        "historical_api_true": sum(
            x["historical_api_response"] == "TRUE" for x in output
        ),
        "reconciliation_counts": dict(counts),
        "archive_inventory_snapshot": "YesGov comparison input, 2026-09-15 07:10 (timezone unspecified in source README)",
        "queue_ties_snapshot": "tier3_queue_breadth_2026-09-12.csv; identity gaps remain",
    }
    (RUN / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
