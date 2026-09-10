"""WO-175 step 1: fetch each rejected channel's About page from WO-171's
own channel-verdict list (rtr-business/research/wo171_channel_verdicts.csv,
verdict == "rejected", 287 channels) and pull out the signal needed to
hand-check it against the government it was assigned to: the channel's
own title, description, and keywords.

Ryan's ask (WO-171 rejected 287 of 1,010 LocalView channels -- 31 for an
unreachable oEmbed call, the rest for an author name that did not
plainly match the government): hand-check them, and where the channel
really is the government's own (or a shared/community channel that
also carries its meetings), find a different, more clearly on-mission
video on it rather than trusting the one WO-171 happened to sample. This
script is the first of three: fetch (this file), classify
(wo175_classify_channels.py), then find-and-queue
(wo175_find_and_queue_video.py).

The channel's About page (`https://www.youtube.com/{handle}/about`)
renders its `channelMetadataRenderer` (title, description, keywords)
server-side in `ytInitialData`, no headless browser needed -- confirmed
live against a real government channel (@CityofAndalusia) and a real
rejected one (@ClayGBeatz) building this script. One GET per channel,
2 seconds apart (CLAUDE.md's "we query sites politely" convention),
stopping outright on YouTube's block signature (429, or "Sign in to
confirm you're not a bot" -- see docs/investigations/youtube_429_block.md)
and after 6 consecutive errors.

Writes rtr-business/research/wo175_about_fetch.csv (resumable: a
channel_id already present is skipped on a re-run).

Usage:
    python scripts/wo175_fetch_about_pages.py
"""

import csv
import re
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
BUSINESS_RESEARCH = Path.home() / "Documents" / "rtr-business" / "research"

VERDICTS_CSV = BUSINESS_RESEARCH / "wo171_channel_verdicts.csv"
OUT_CSV = BUSINESS_RESEARCH / "wo175_about_fetch.csv"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

TITLE_RE = re.compile(r'"channelMetadataRenderer":\{"title":"((?:[^"\\]|\\.)*)"')
DESC_RE = re.compile(
    r'"channelMetadataRenderer":\{"title":"(?:[^"\\]|\\.)*","description":"((?:[^"\\]|\\.)*)"'
)
KEYWORDS_RE = re.compile(r'"keywords":"((?:[^"\\]|\\.)*)"')
BLOCK_RE = re.compile(
    r"Sign in to confirm|Verify you.re not a bot|unusual traffic", re.I
)

FIELDS = [
    "channel_id",
    "handle",
    "http_status",
    "title",
    "description",
    "keywords",
    "error",
]


def unescape(s: str) -> str:
    return (
        s.replace("\\u0026", "&")
        .replace("\\/", "/")
        .replace('\\"', '"')
        .replace("\\n", " ")
    )


def load_done() -> set:
    done = set()
    if OUT_CSV.exists():
        with OUT_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                done.add(r["channel_id"])
    return done


def main() -> None:
    with VERDICTS_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rejected = [r for r in rows if r["verdict"] == "rejected"]
    print(f"{len(rejected)} rejected channels total")

    done = load_done()
    is_new = not OUT_CSV.exists()
    consec_errors = 0

    with OUT_CSV.open("a", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=FIELDS, lineterminator="\n")
        if is_new:
            writer.writeheader()

        for i, row in enumerate(rejected):
            cid = row["channel_id"]
            handle = row["handle"]
            if cid in done:
                continue
            # WO-171 never resolved a @handle for the 31 originally
            # oEmbed-unreachable channels -- falling back to the
            # permanent channel_id path here is what actually made 30
            # of those 31 reachable (confirmed live 2026-09-10; see
            # wo175_methods_section.md). A blank handle would otherwise
            # build "https://www.youtube.com/ /about" and silently come
            # back "no channel data parsed" on a real 200.
            path = f"@{handle.lstrip('@')}" if handle.strip() else f"channel/{cid}"
            url = f"https://www.youtube.com/{path}/about"
            try:
                resp = requests.get(url, headers={"User-Agent": UA}, timeout=20)
                status = resp.status_code
                text = resp.text
                if BLOCK_RE.search(text):
                    print(f"[BLOCK SIGNATURE] {handle} -- stopping all YouTube calls")
                    out_f.flush()
                    sys.exit(2)
                title_m = TITLE_RE.search(text)
                desc_m = DESC_RE.search(text)
                kw_m = KEYWORDS_RE.search(text)
                title = unescape(title_m.group(1)) if title_m else ""
                desc = unescape(desc_m.group(1)) if desc_m else ""
                kw = unescape(kw_m.group(1)) if kw_m else ""
                err = (
                    ""
                    if (status == 200 and title)
                    else f"no channel data parsed (status {status})"
                )
                writer.writerow(
                    {
                        "channel_id": cid,
                        "handle": handle,
                        "http_status": status,
                        "title": title,
                        "description": desc,
                        "keywords": kw,
                        "error": err,
                    }
                )
                print(f"[{i + 1}/{len(rejected)}] {handle} -> title={title!r}")
                consec_errors = 0 if not err else consec_errors + 1
            except Exception as e:
                writer.writerow(
                    {
                        "channel_id": cid,
                        "handle": handle,
                        "http_status": "",
                        "title": "",
                        "description": "",
                        "keywords": "",
                        "error": str(e),
                    }
                )
                print(f"[{i + 1}/{len(rejected)}] {handle} -> ERROR {e}")
                consec_errors += 1

            out_f.flush()
            if consec_errors >= 6:
                print("6 consecutive errors -- stopping.")
                sys.exit(3)
            time.sleep(2)


if __name__ == "__main__":
    main()
