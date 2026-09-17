"""Evidence-scoped identity matches and proposed Legistar research actions."""

import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parent.parent
)  # repo root (this script now lives in scripts/)
RUN = ROOT / "research_runs" / "legistar_clients_2026-09-15"
BUS = Path("/Users/mroconnell/Documents/rtr-business/research")


def rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def jsonl(path):
    if not path.exists():
        return {}
    return {
        x["client"]: x
        for x in (
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        )
    }


STATES = {
    x["state"]: x["name"]
    for x in rows(ROOT / "app/utils/jurisdiction_data/us_states.csv")
}
STATES.update(
    {
        "ON": "Ontario",
        "QC": "Quebec",
        "BC": "British Columbia",
        "AB": "Alberta",
        "MB": "Manitoba",
        "SK": "Saskatchewan",
        "NS": "Nova Scotia",
        "NB": "New Brunswick",
    }
)


def state_from(title, text):
    combined = (text or "")[:1500] + "\n" + (title or "")
    match = re.search(r",\s*([A-Z]{2})\s*\d{5}\b", combined)
    if match and match.group(1) in STATES:
        return STATES[match.group(1)], "agenda-address"
    match = re.search(r",\s*([A-Z]{2})\b", title or "")
    if match and match.group(1) in STATES:
        return STATES[match.group(1)], "calendar-explicit-state-abbreviation"
    for abbr, name in STATES.items():
        if re.search(r",\s*" + re.escape(name) + r"\b", title or "", re.I):
            return name, "calendar-explicit-state-name"
        if re.search(
            r",\s*" + re.escape(name) + r"\b(?:\s*\d{5})?", (text or "")[:1500], re.I
        ):
            return name, "agenda-location-state-name"
    return "", ""


def normalize(name):
    name = re.sub(r"\s+[-–]\s+.*", "", name or "", flags=re.I)
    name = re.sub(
        r"\b(?:city|county|village|town|township|borough|district|of|the|government|metro|metropolitan|council|board|meeting|meetings|information|records)\b",
        " ",
        name,
        flags=re.I,
    )
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def govt_type(name):
    x = (name or "").lower()
    if "county" in x:
        return "county"
    if any(y in x for y in ["school district", "schools"]):
        return "school"
    if (
        "district" in x
        or "authority" in x
        or "agency" in x
        or "transit" in x
        or "port of" in x
    ):
        return "agency"
    if "township" in x:
        return "township"
    if "village" in x:
        return "village"
    if "town" in x:
        return "town"
    if "city" in x:
        return "city"
    return ""


def compatible_type(source_type, row):
    name = row.get("city_name", "").lower()
    if source_type == "county":
        return "county" in name
    if source_type == "school":
        return "school" in name or row.get("gov_id", "").startswith("us:sd:")
    if source_type == "agency":
        return any(
            x in name for x in ["district", "authority", "agency", "transit", "port"]
        )
    if source_type == "township":
        return "township" in name or row.get("gov_id", "").startswith("us:cousub:")
    if source_type in {"city", "town", "village"}:
        return (
            any(x in name for x in ["city", "town", "village", "municipality"])
            or source_type == "town"
            and row.get("gov_id", "").startswith("us:cousub:")
        )
    return True


def main():
    static = rows(RUN / "static_reconciliation.csv")
    live = jsonl(RUN / "live_probe.jsonl")
    detail = jsonl(RUN / "detail_probe.jsonl")
    redirect = jsonl(RUN / "video_redirect_probe.jsonl")
    rss = jsonl(RUN / "rss_probe.jsonl")
    agenda = jsonl(RUN / "agenda_identity.jsonl")
    jc = rows(BUS / "jurisdiction_coverage.csv")
    archive = []
    with gzip.open(
        BUS / "yesgov_2026-09-15/inputs/meeting_inventory.csv.gz",
        "rt",
        newline="",
        encoding="utf-8",
    ) as f:
        archive = list(csv.DictReader(f))
    archive_gov_video = defaultdict(list)
    archive_video_host = defaultdict(list)
    for row in archive:
        if row.get("has_video") == "yes" and row.get("gov_id"):
            archive_gov_video[row["gov_id"]].append(row)
        if row.get("has_video") == "yes":
            from urllib.parse import urlparse

            for url_field in ["source_url", "video_url"]:
                host = urlparse(row.get(url_field, "")).hostname
                if host:
                    archive_video_host[host].append(row)
    jc_by_id = {x["gov_id"]: x for x in jc if x.get("gov_id")}
    by_state_norm = defaultdict(list)
    by_norm = defaultdict(list)
    for row in jc:
        key = normalize(row.get("city_name", ""))
        by_norm[key].append(row)
        by_state_norm[(row.get("state_or_province", ""), key)].append(row)

    out = []
    for source in static:
        c = source["client"]
        live_row = live.get(c, {})
        d = detail.get(c, {})
        r = redirect.get(c, {})
        feed = rss.get(c, {})
        a = agenda.get(c, {})
        title = live_row.get("calendar", {}).get("title", "")
        pdf_text = a.get("first_page_text", "")
        state, state_basis = state_from(title, pdf_text)
        source_type = govt_type(title or pdf_text[:150])
        title_clean = re.sub(r"\s+[-–]\s+.*", "", title, flags=re.I)
        for state_name in STATES.values():
            title_clean = re.sub(
                r"(?:,\s*|\s+)" + re.escape(state_name) + r"\s*$",
                "",
                title_clean,
                flags=re.I,
            )
        title_clean = re.sub(r",\s*[A-Z]{2}\s*$", "", title_clean)
        key = normalize(title_clean)
        exact = (
            [
                x
                for x in by_state_norm.get((state, key), [])
                if compatible_type(source_type, x)
            ]
            if state and key
            else []
        )
        possible = (
            [x for x in by_norm.get(key, []) if compatible_type(source_type, x)]
            if key
            else []
        )
        match = exact[0] if len({x.get("gov_id") for x in exact}) == 1 else None
        if c == "louisville" and state == "Kentucky":
            match = jc_by_id.get(
                "us:place:2148006"
            )  # Louisville/Jefferson County metro government (balance), first-party agenda location
        archive_page = (
            archive_gov_video[match["gov_id"]][0]
            if match and archive_gov_video[match["gov_id"]]
            else None
        )
        detail_status = d.get("http_status", "")
        clip = (
            r.get("http_status") == 200
            and r.get("final_host", "").endswith(".granicus.com")
            and (
                "/player/clip/" in r.get("final_url", "")
                or "MediaPlayer.php" in r.get("final_url", "")
                and "clip_id=" in r.get("final_url", "")
            )
        )
        delegated_archive_page = (
            archive_video_host[r.get("final_host", "")][0]
            if clip and archive_video_host[r.get("final_host", "")]
            else None
        )
        youtube_only = bool(d.get("youtube_leads")) and not clip
        if source["reconciliation_status"] == "archive-video-evidence":
            final = "excluded-archive-video-direct-tenant"
        elif source["reconciliation_status"] == "existing-legistar-platform-and-hub":
            final = "excluded-recorded-legistar-hub"
        elif source["reconciliation_status"] == "ambiguous-existing-government-match":
            final = "held-ambiguous-existing-association"
        elif clip and delegated_archive_page:
            final = "excluded-archive-video-delegated-host"
        elif clip:
            final = "clip-page-not-in-archive-host"
        elif r.get("final_url", "").endswith("/Error.aspx"):
            final = "video-link-to-error-page"
        elif youtube_only:
            final = "youtube-lead-no-fetch"
        elif detail_status == 200:
            final = "detail-page-no-video-link-on-selected-event"
        elif detail_status == 410:
            final = "selected-detail-http-410"
        else:
            final = "no-usable-selected-detail"
        if c in {"madison", "pinellas", "pomona"}:
            identity_action = "repair-wrong-government-research-association"
        elif match and archive_page:
            identity_action = "existing-government-already-archive-video"
        elif match:
            identity_action = "existing-government-add-or-review-legistar-hub"
        elif state and pdf_text and len(exact) == 0:
            identity_action = (
                "verified-location-no-exact-research-row-review-new-government"
            )
        elif len(possible) == 1:
            identity_action = "possible-research-match-state-unverified"
        else:
            identity_action = "identity-held-for-review"
        out.append(
            {
                "client": c,
                "historical_api_response": source["historical_api_response"],
                "static_status": source["reconciliation_status"],
                "final_test_outcome": final,
                "identity_action": identity_action,
                "calendar_title": title,
                "identity_state": state,
                "identity_state_basis": state_basis,
                "source_government_type": source_type,
                "matched_gov_id": match.get("gov_id", "") if match else "",
                "matched_government_name": match.get("city_name", "") if match else "",
                "possible_gov_ids": "|".join(
                    sorted({x.get("gov_id", "") for x in possible})
                )[:350],
                "archive_video_source_url": archive_page.get("source_url", "")
                if archive_page
                else "",
                "delegated_host_archive_video_url": delegated_archive_page.get(
                    "source_url", ""
                )
                if delegated_archive_page
                else "",
                "calendar_url": live_row.get("calendar", {}).get("url", ""),
                "detail_url": d.get("detail_url", ""),
                "detail_http_status": detail_status,
                "event_body": d.get("event", {}).get("EventBodyName", ""),
                "event_date": (d.get("event", {}).get("EventDate") or "")[:10],
                "video_url": d.get("video_url", ""),
                "granicus_clip_url": r.get("final_url", "") if clip else "",
                "observed_view_id": r.get("view_id_from_url", ""),
                "rss_video_real_items": feed.get("video_mode", {}).get(
                    "real_item_count", ""
                ),
                "rss_podcast_real_items": feed.get("podcast_mode", {}).get(
                    "real_item_count", ""
                ),
                "rss_video_first_item_link": feed.get("video_mode", {}).get(
                    "first_item_link", ""
                ),
                "agenda_url": a.get("agenda_url", ""),
                "agenda_pdf_sha256": a.get("pdf_sha256", ""),
                "agenda_first_page_excerpt": pdf_text[:600].replace("\n", " | "),
                "youtube_leads": "|".join(d.get("youtube_leads", []))[:550],
                "raw_error": " | ".join(
                    filter(
                        None,
                        [
                            live_row.get("api_bodies", {}).get("error", ""),
                            live_row.get("calendar", {}).get("error", ""),
                            d.get("error", ""),
                            r.get("error", ""),
                            a.get("error", ""),
                        ],
                    )
                )[:550],
            }
        )
    with (RUN / "identity_reconciliation.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(
        "clients",
        len(out),
        "final",
        Counter(x["final_test_outcome"] for x in out),
        "identity",
        Counter(x["identity_action"] for x in out),
    )


if __name__ == "__main__":
    main()
