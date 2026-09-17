"""Create reviewable journals and a same-unit 286-client report."""

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parent.parent
)  # repo root (this script now lives in scripts/)
RUN = ROOT / "research_runs" / "legistar_clients_2026-09-15"
BUS = Path("/Users/mroconnell/Documents/rtr-business/research")


def read(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(name, rows, fields):
    with (RUN / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    recon = read(RUN / "identity_reconciliation.csv")
    by_client = {x["client"]: x for x in recon}
    jc = {
        x["gov_id"]: x
        for x in read(BUS / "jurisdiction_coverage.csv")
        if x.get("gov_id")
    }
    changes = []

    def propose(gov_id, field, value, evidence, reason, action="review-cell-update"):
        row = jc.get(gov_id, {})
        changes.append(
            {
                "action": action,
                "gov_id": gov_id,
                "government": row.get("city_name", ""),
                "state_or_province": row.get("state_or_province", ""),
                "field": field,
                "current_value_at_diagnostic": row.get(field, ""),
                "proposed_value": value,
                "source_url": evidence,
                "reason": reason,
                "writer_status": "proposed-only; reconcile-fresh-row",
            }
        )

    mad = by_client["madison"]
    pin = by_client["pinellas"]
    pom = by_client["pomona"]
    propose(
        "us:county:21151",
        "example_agenda_or_calendar_url",
        "",
        mad["agenda_url"],
        "Madison tenant agenda cover identifies City of Madison WI, not Madison County KY",
    )
    propose(
        "us:county:21151",
        "suspected_meeting_link_provider",
        "",
        mad["agenda_url"],
        "Tenant-derived Legistar label belongs to Madison WI; preserve legitimate Kentucky primary",
    )
    propose(
        "us:place:1228175",
        "domain",
        "mygulfport.us",
        "https://mygulfport.us/",
        "Official Gulfport FL homepage; Pinellas tenant belongs to Pinellas County FL",
    )
    propose(
        "us:place:1228175",
        "example_meeting_url",
        "",
        pin["agenda_url"],
        "Pinellas County calendar is a wrong-government meeting URL",
    )
    propose(
        "us:place:1228175",
        "suspected_video_provider",
        "",
        pin["agenda_url"],
        "Legistar provider label came from wrong Pinellas County tenant; reevaluate from Gulfport evidence",
    )
    propose(
        "us:place:1228175",
        "reject_reason",
        "review-current-coverage",
        pin["agenda_url"],
        "Current already-covered label appears tied to wrong Pinellas tenant; writer should determine exact replacement label",
    )
    propose(
        "us:place:3658992",
        "example_agenda_or_calendar_url",
        "",
        pom["agenda_url"],
        "Pomona tenant agenda cover identifies City of Pomona CA, not Pomona village NY",
    )
    propose(
        "us:place:3658992",
        "suspected_meeting_link_provider",
        "",
        pom["agenda_url"],
        "Tenant-derived Legistar provider belongs to Pomona CA; retain official village primary",
    )
    propose(
        "us:place:0658072",
        "example_agenda_or_calendar_url",
        "https://pomona.legistar.com/Calendar.aspx",
        pom["agenda_url"],
        "Agenda cover identifies City of Pomona CA and a public Legistar calendar",
    )
    propose(
        "us:place:0658072",
        "suspected_meeting_link_provider",
        "legistar",
        pom["agenda_url"],
        "First-party city calendar and agenda cover; video not verified for selected event",
    )

    for client, name, state, owner_type in [
        (
            "portofoakland",
            "Port of Oakland",
            "California",
            "independent City of Oakland department; canonical ID/type pending",
        ),
        (
            "sbcera",
            "San Bernardino County Employees' Retirement Association",
            "California",
            "independent government entity; canonical ID pending",
        ),
    ]:
        row = by_client[client]
        changes.append(
            {
                "action": "review-new-government-row",
                "gov_id": "PENDING_CANONICAL_ID",
                "government": name,
                "state_or_province": state,
                "field": "new-row-proposal",
                "current_value_at_diagnostic": "no matching research row",
                "proposed_value": f"domain={client}.legistar.com; example_agenda_or_calendar_url=https://{client}.legistar.com/Calendar.aspx; suspected_meeting_link_provider=legistar; suspected_video_provider=granicus; government_type={owner_type}",
                "source_url": row["agenda_url"] + " | " + row["granicus_clip_url"],
                "reason": "First-party agenda cover verifies owner and location; past meeting link redirects to a 200 Granicus clip; observed-view video RSS has real clip items. Do not invent ID or claim transcript.",
                "writer_status": "proposed-only; resolve canonical ID and live Archive/queue first",
            }
        )
    write("proposed_cell_updates.csv", changes, list(changes[0]))

    youtube = []
    for row in recon:
        for url in row["youtube_leads"].split("|") if row["youtube_leads"] else []:
            if url:
                youtube.append(
                    {
                        "client": row["client"],
                        "gov_id_if_verified": row["matched_gov_id"],
                        "source_detail_url": row["detail_url"],
                        "youtube_url": url,
                        "verified": "false",
                        "next_action": "existing-local-youtube-drip-lane",
                        "note": "link discovered in Legistar HTML; YouTube content not fetched",
                    }
                )
    write(
        "youtube_leads_unfetched.csv",
        youtube,
        list(youtube[0]) if youtube else ["client", "youtube_url"],
    )

    final = Counter(x["final_test_outcome"] for x in recon)
    assert sum(final.values()) == 286
    source = json.loads((RUN / "source_manifest.json").read_text())
    lines = [
        "# Legistar client enumeration — September 15, 2026",
        "",
        "Tested the author-supplied Legistar client strings to find video-backed public meetings and identify governments. The author file contains 286 distinct clients; its historical `api` flag records whether a bodies request answered in 2024, not video.",
        "",
        "## Source",
        "",
        f"Author dataset: {source['source_url']}",
        f"Repository revision: `{source['author_repo_revision']}`; source SHA-256: `{source['source_sha256']}`; author last updated 2024-05-12.",
        "R loaded 286 rows: 176 historical API TRUE, 110 FALSE.",
        "",
        "## Steps — unit: one author client",
        "",
        "| Step | Outcome | Clients |",
        "|---|---|---:|",
        "| Static reconciliation | Direct Legistar tenant has Archive video evidence (dated snapshot) | 12 |",
        "| | Recorded Legistar platform and hub, held out of enumeration | 5 |",
        "| | Ambiguous existing-government association, held | 1 |",
        "| | Proceeded to bounded API/calendar/detail checks | 268 |",
        "| | **Total** | **286** |",
        "",
        "The 268 checked clients had 257 current bodies API HTTP 200 responses, 9 HTTP 500 responses, and 2 HTTP 403 responses. All 268 calendar requests returned HTTP 200, but only 265 carried a Legistar meeting-page signal. These are route outcomes, not video findings.",
        "",
        "## Final outcome — unit: one author client",
        "",
        "| Mutually exclusive outcome | Clients |",
        "|---|---:|",
        f"| Archive video on direct Legistar tenant | {final['excluded-archive-video-direct-tenant']} |",
        f"| Archive video on exact delegated Granicus host | {final['excluded-archive-video-delegated-host']} |",
        f"| Existing recorded Legistar platform and hub | {final['excluded-recorded-legistar-hub']} |",
        f"| Ambiguous existing-government association | {final['held-ambiguous-existing-association']} |",
        f"| Granicus clip destination not in dated Archive host inventory | {final['clip-page-not-in-archive-host']} |",
        f"| Video link landed on error page | {final['video-link-to-error-page']} |",
        f"| YouTube lead only, not fetched | {final['youtube-lead-no-fetch']} |",
        f"| Selected meeting detail lacked a video link | {final['detail-page-no-video-link-on-selected-event']} |",
        f"| Selected detail returned HTTP 410 | {final['selected-detail-http-410']} |",
        f"| No usable selected detail | {final['no-usable-selected-detail']} |",
        "| **Total** | **286** |",
        "",
        "One selected meeting per client was checked. A no-link result does not establish that a tenant publishes no recordings. The 10 YouTube-only outcomes are a subset of the isolated unfetched lead sidecar; other pages also exposed YouTube links. Three selected detail pages also carried audio-shaped links; they were kept separate from `Mode2=Video` and audio playback was not tested. Granicus clip pages and RSS enclosures were read-only evidence; transcripts and playback were not resolved or ingested.",
        "",
        "## Findings requiring review",
        "",
        "Five video-link routes reached Granicus clip pages on hosts absent from the dated Archive video inventory. Franklin TN, St. Charles Parish LA and Westchester County NY already have Archive video under other hosts, so they are alternate-source findings. Port of Oakland and SBCERA are the strongest new public-body leads; both have first-party agenda covers, a 200 Granicus clip destination, and real observed-view RSS video items. Port is an independent City of Oakland department; SBCERA states it is an independent government entity. Their canonical ID/type decisions belong to the coordinating identity process.",
        "",
        "Three historical research associations require repair: `madison` belongs to Madison city WI, not Madison County KY; `pinellas` belongs to Pinellas County FL, not Gulfport city FL; `pomona` belongs to Pomona city CA, not Pomona village NY. First-party agenda PDFs establish all three locations. Exact proposed fields are in proposed_cell_updates.csv; no shared research cells were edited here.",
        "",
        "Observed Granicus RSS was checked in both video and podcast modes for the 96 clip routes with real `view_id`s from redirects. All 96 feeds returned HTTP 200 in both modes; 95 video-mode feeds had real clip items and one was empty. Populated podcast feeds reported the same WMV MIME type as video mode, so the mode name alone is not audio proof. No `view_id`s were guessed.",
        "",
        "The September 15 Archive inventory is a 07:10 snapshot with timezone unspecified in its source README. Current queue files were read locally; accepted video-probe queue URLs had no exact destination-host match here, but government identity gaps remain. Reconcile live Archive and queues before research writes. No YouTube was fetched, no challenge was bypassed, and no Archive ingest, queueing, shared lead writes or app code changes were made.",
        "",
        "## Audit corrections",
        "",
        "The initial static join marked eight recorded Legistar platform+hub clients as exclusions. Identity review reopened `madison`, `pinellas`, and `pomona`; agenda covers proved their research associations wrong, leaving five safe recorded-hub exclusions. The first 62 API/calendar wrapper rows had five non-200 responses logged as blank because of an HTTP-library boolean check. Those original rows are preserved in `live_probe_initial_status_gap.jsonl`, the logging was corrected, and all five clients were rerun. The first three RSS rows lacked enclosure MIME types; they are preserved in `rss_probe_initial_no_mime.jsonl` and were rerun with MIME extraction. No corrected row is counted twice.",
        "",
        "## Files",
        "",
        "legistar_clients.rda; legistar_clients.csv; source_manifest.json; static_reconciliation.csv; live_probe.jsonl; detail_probe.jsonl; video_redirect_probe.jsonl; rss_probe.jsonl; agenda_identity.jsonl; identity_reconciliation.csv; proposed_cell_updates.csv; youtube_leads_unfetched.csv; agenda_identity_pdfs/.",
    ]
    (RUN / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("final", final, "proposed rows", len(changes), "youtube URLs", len(youtube))


if __name__ == "__main__":
    main()
