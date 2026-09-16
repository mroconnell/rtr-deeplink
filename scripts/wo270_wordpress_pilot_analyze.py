#!/usr/bin/env python3
"""WO-270 analysis: compute endpoint availability, signal hit/FP rates,
and the "which surface reached the known video" tally from a
wo270_wordpress_pilot.py run's wo270_probe_results.csv /
wo270_site_summary.csv.

Usage: `python scripts/wo270_wordpress_pilot_analyze.py [data_dir]`
(data_dir defaults to cwd; it's where the two CSVs above live)."""

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from wo270_wordpress_pilot import STRICT_VIDEO_MARKERS  # noqa: E402

DATA_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
RESULTS = DATA_DIR / "wo270_probe_results.csv"
SUMMARY = DATA_DIR / "wo270_site_summary.csv"


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(n, d):
    return f"{n / d:.3f}" if d else "n/a"


def main():
    results = load(RESULTS)
    summary = load(SUMMARY)
    pos = [s for s in summary if s["set"] == "positive"]
    neg = [s for s in summary if s["set"] == "negative"]
    print(f"Total sites: {len(summary)} (positive={len(pos)}, negative={len(neg)})")

    # (a) endpoint availability -- outcome counts per probe GROUP
    def group_of(probe):
        if probe == "feed":
            return "feed"
        if probe == "wp_json_root":
            return "wp_json_root"
        if probe == "wp_json_types":
            return "wp_json_types"
        if probe.startswith("posts_search_"):
            return "posts_search"
        if probe.startswith("media_"):
            return "media"
        if probe == "events":
            return "events"
        if probe.startswith("sitemap_"):
            return "sitemap"
        if probe.startswith("site_search_"):
            return "site_search"
        if probe == "front_page":
            return "front_page"
        return probe

    outcome_by_group = defaultdict(Counter)
    sites_by_group_outcome = defaultdict(lambda: defaultdict(set))
    for r in results:
        g = group_of(r["probe"])
        outcome_by_group[g][r["outcome"]] += 1
        sites_by_group_outcome[g][r["outcome"]].add(r["domain"])

    print("\n=== (a) Endpoint availability (row-count, all probes in group) ===")
    for g in [
        "feed",
        "wp_json_root",
        "wp_json_types",
        "posts_search",
        "media",
        "events",
        "sitemap",
        "site_search",
        "front_page",
    ]:
        print(f"-- {g} --")
        for outcome, n in outcome_by_group[g].most_common():
            print(f"   {outcome}: {n}")

    print("\n=== (a2) Endpoint availability by DISTINCT SITE (out of 277) ===")
    for g in [
        "feed",
        "wp_json_root",
        "wp_json_types",
        "posts_search",
        "media",
        "events",
        "sitemap",
        "site_search",
        "front_page",
    ]:
        answered_sites = sites_by_group_outcome[g].get("answered", set())
        html_fallback_sites = sites_by_group_outcome[g].get(
            "answered_html_fallback", set()
        )
        print(
            f"{g}: answered={len(answered_sites)} html_fallback={len(html_fallback_sites)}"
        )

    # (b) signal hit rate / FP rate on summary fields
    def rate(rows, field, truthy=lambda v: v not in ("", "False", "0", None)):
        n = sum(1 for r in rows if truthy(r.get(field, "")))
        return n, len(rows)

    def bool_field(rows, field):
        return rate(rows, field, truthy=lambda v: v == "True")

    def nonempty_field(rows, field):
        return rate(rows, field, truthy=lambda v: bool(v.strip()) if v else False)

    def count_field_gt0(rows, field):
        return rate(rows, field, truthy=lambda v: v.strip() not in ("", "0"))

    print(
        "\n=== (b) Candidate signal hit-rate (positive) vs false-positive-rate (negative) ==="
    )
    candidates = [
        (
            "feed_video_marker BROAD (any marker word in /feed/)",
            "feed_video_markers",
            nonempty_field,
        ),
        (
            "feed_video_marker STRICT (youtube/vimeo/mp4/zoom link in /feed/)",
            "feed_strict_video_markers",
            nonempty_field,
        ),
        (
            "feed_meeting_word (any meeting word in /feed/)",
            "feed_meeting_words",
            nonempty_field,
        ),
        (
            "posts_search_video_marker BROAD (any word search)",
            "posts_search_video_marker_words",
            nonempty_field,
        ),
        (
            "posts_search_video_marker STRICT (any word search)",
            "posts_search_strict_video_markers",
            nonempty_field,
        ),
        ("posts_search_agenda_count>0", "posts_search_agenda_count", count_field_gt0),
        ("posts_search_minutes_count>0", "posts_search_minutes_count", count_field_gt0),
        ("posts_search_meeting_count>0", "posts_search_meeting_count", count_field_gt0),
        ("posts_search_video_count>0", "posts_search_video_count", count_field_gt0),
        ("posts_search_youtube_count>0", "posts_search_youtube_count", count_field_gt0),
        (
            "posts_search_recording_count>0",
            "posts_search_recording_count",
            count_field_gt0,
        ),
        ("media_video_count>0", "media_video_count", count_field_gt0),
        ("media_audio_count>0", "media_audio_count", count_field_gt0),
        ("events_found_video_marker", "events_found_video_marker", bool_field),
        (
            "sitemap_interesting (meeting/agenda/event sub-sitemap)",
            "sitemap_interesting",
            nonempty_field,
        ),
        (
            "site_search_video_marker BROAD (any /?s= word)",
            "site_search_video_marker_words",
            nonempty_field,
        ),
        (
            "site_search_video_marker STRICT (any /?s= word)",
            "site_search_strict_video_markers",
            nonempty_field,
        ),
        ("front_page_video_marker BROAD", "front_page_video_marker", bool_field),
        (
            "front_page_video_marker STRICT",
            "front_page_strict_video_markers",
            nonempty_field,
        ),
        (
            "interesting_post_types (meeting/agenda/minutes/event/video type)",
            "interesting_post_types",
            nonempty_field,
        ),
    ]
    for label, field, fn in candidates:
        hp, dp = fn(pos, field)
        hn, dn = fn(neg, field)
        print(f"{label}: hit={hp}/{dp} ({pct(hp, dp)})  FP={hn}/{dn} ({pct(hn, dn)})")

    # per-pattern breakdown within the strict marker set, across every surface
    print(
        "\n=== Per-pattern breakdown (STRICT markers only, combined across feed+posts_search+site_search+front_page) ==="
    )
    strict_fields = [
        "feed_strict_video_markers",
        "posts_search_strict_video_markers",
        "site_search_strict_video_markers",
        "front_page_strict_video_markers",
    ]

    def combined_strict_patterns(row):
        pats = set()
        for f in strict_fields:
            for p in (row.get(f) or "").split(";"):
                if p:
                    pats.add(p)
        return pats

    for pat in STRICT_VIDEO_MARKERS:
        hp = sum(1 for r in pos if pat in combined_strict_patterns(r))
        hn = sum(1 for r in neg if pat in combined_strict_patterns(r))
        print(
            f"  {pat}: hit={hp}/{len(pos)} ({pct(hp, len(pos))})  FP={hn}/{len(neg)} ({pct(hn, len(neg))})"
        )

    # combined "any strict marker anywhere" signal
    any_strict_pos = sum(1 for r in pos if combined_strict_patterns(r))
    any_strict_neg = sum(1 for r in neg if combined_strict_patterns(r))
    print(
        f"\nANY strict marker on ANY surface: hit={any_strict_pos}/{len(pos)} ({pct(any_strict_pos, len(pos))})  FP={any_strict_neg}/{len(neg)} ({pct(any_strict_neg, len(neg))})"
    )

    # front page plugin correlation
    print("\n=== Front-page plugin names: frequency in positive vs negative ===")
    plugin_counter_pos = Counter()
    plugin_counter_neg = Counter()
    for r in pos:
        for p in (r.get("front_page_plugins") or "").split(";"):
            if p:
                plugin_counter_pos[p] += 1
    for r in neg:
        for p in (r.get("front_page_plugins") or "").split(";"):
            if p:
                plugin_counter_neg[p] += 1
    all_plugins = set(plugin_counter_pos) | set(plugin_counter_neg)
    rows = []
    for p in all_plugins:
        rows.append((p, plugin_counter_pos.get(p, 0), plugin_counter_neg.get(p, 0)))
    rows.sort(key=lambda x: -(x[1]))
    for p, cp, cn in rows[:30]:
        print(f"  {p}: positive={cp}/{len(pos)} negative={cn}/{len(neg)}")

    # theme correlation
    print("\n=== Front-page theme: frequency ===")
    theme_pos = Counter(
        r.get("front_page_theme") for r in pos if r.get("front_page_theme")
    )
    theme_neg = Counter(
        r.get("front_page_theme") for r in neg if r.get("front_page_theme")
    )
    for t, c in theme_pos.most_common(15):
        print(f"  {t}: positive={c} negative={theme_neg.get(t, 0)}")

    # namespaces correlation
    print("\n=== wp-json namespaces: frequency ===")
    ns_pos = Counter()
    ns_neg = Counter()
    for r in pos:
        for ns in (r.get("wp_json_namespaces") or "").split(";"):
            if ns:
                ns_pos[ns] += 1
    for r in neg:
        for ns in (r.get("wp_json_namespaces") or "").split(";"):
            if ns:
                ns_neg[ns] += 1
    all_ns = set(ns_pos) | set(ns_neg)
    ns_rows = sorted(all_ns, key=lambda n: -(ns_pos.get(n, 0)))
    for n in ns_rows[:30]:
        print(
            f"  {n}: positive={ns_pos.get(n, 0)}/{len(pos)} negative={ns_neg.get(n, 0)}/{len(neg)}"
        )

    # custom post types correlation
    print("\n=== custom post types: frequency ===")
    cpt_pos = Counter()
    cpt_neg = Counter()
    for r in pos:
        for t in (r.get("custom_post_types") or "").split(";"):
            if t:
                cpt_pos[t] += 1
    for r in neg:
        for t in (r.get("custom_post_types") or "").split(";"):
            if t:
                cpt_neg[t] += 1
    interesting = {
        "meeting",
        "agenda",
        "minutes",
        "event",
        "video",
        "tribe_events",
        "mec-events",
        "mec_events",
        "council",
        "board",
    }
    for t in sorted(set(cpt_pos) | set(cpt_neg), key=lambda t: -(cpt_pos.get(t, 0))):
        if cpt_pos.get(t, 0) > 0 or t in interesting:
            print(
                f"  {t}: positive={cpt_pos.get(t, 0)}/{len(pos)} negative={cpt_neg.get(t, 0)}/{len(neg)}"
            )

    # (c) which surface reached the known video, for positives
    print(
        "\n=== (c) Which surface reached the known video (positives only, n=%d) ==="
        % len(pos)
    )
    surface_counter = Counter()
    any_surface = 0
    for r in pos:
        surfaces = (r.get("known_video_surfaces_reached") or "").strip()
        if surfaces:
            any_surface += 1
            for s in surfaces.split(";"):
                surface_counter[s] += 1
        else:
            surface_counter["NONE"] += 1
    for s, c in surface_counter.most_common():
        print(f"  {s}: {c}")
    print(f"  (any surface reached it: {any_surface}/{len(pos)})")

    # host-stopped reasons
    print("\n=== Host-stop reasons (all sites) ===")
    stop_counter = Counter(r.get("host_stopped_reason") or "(none)" for r in summary)
    for reason, c in stop_counter.most_common():
        print(f"  {reason}: {c}")

    # errors
    print("\n=== Sites with fetch errors (missing most fields) ===")
    error_sites = [r for r in summary if "error" in r and r.get("error")]
    print(f"count={len(error_sites)}")
    for r in error_sites[:20]:
        print(f"  {r['domain']} ({r['set']}): {r.get('error')}")


if __name__ == "__main__":
    main()
