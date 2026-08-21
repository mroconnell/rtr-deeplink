"""Processed-message-ID ledger for the daily Gmail inbox-triage Routine
(WO-33). Replaces the `rtr-claude-processed` Gmail label entirely.

Why this exists: the Routine used to mark work done by calling
`label_thread`, a Gmail *write* call. Ryan declined Gmail write scope
permanently on 2026-08-21 -- an unattended daily job that opens and merges
its own PRs shouldn't also hold write access to his mailbox -- so that
path is gone for good, not temporarily broken. Without it the Routine
re-reviewed its whole backlog every run (34 threads 2026-08-17, 68 by
2026-08-18, growing daily). The Routine already opens a PR every run, so
it can commit its own ledger instead; that needs no Gmail write at all.
See CLAUDE_INBOX_TRIAGE.md's "Dedupe protocol" section for the run-time
protocol, and its "Open item" section for the decision history.

Design notes, each with a real reason (all four are constraints, not
preferences):

1. **Message IDs, not thread IDs.** Gmail's label semantics are
   thread-level, which is exactly what made `-label:rtr-claude-processed`
   unreliable: a thread holding one processed and one new message still
   comes back from the query. Every 2026-08-19/20/21 run note in
   CLAUDE_INBOX_TRIAGE.md records having to work around that by hand.
   Message IDs are per-message and unambiguous.
2. **Ledger + lookback window, never dates alone.** A pure "newer than
   the last run" filter would silently drop a late-delivered alert --
   failing closed with nobody noticing, the worst failure mode for a
   monitoring-triage job. The ledger is what makes a wide, overlapping
   `newer_than:` window cheap: re-seeing an old message costs one set
   lookup, not a re-review.
3. **Prune past the window** so the file doesn't grow without bound. The
   retention cutoff is deliberately LOOKBACK + GRACE, not LOOKBACK: an
   entry pruned at exactly the window edge could be handed back by the
   very next run (Gmail's `newer_than:` boundary and this script's date
   arithmetic don't have to agree to the hour) and get re-reviewed.
4. **Append-only line format.** `record` only ever appends; nothing
   rewrites the file except `prune`. This repo is worked on by more than
   one session at a time (see CLAUDE.md), and an append conflicts far
   more gracefully than a full-file rewrite of JSON/YAML would.

Usage (from the repo root -- all subcommands read IDs on stdin):

    # 1. which of these message IDs haven't been triaged yet?
    printf '%s\\n' $IDS | python scripts/inbox_triage_ledger.py filter

    # 2. after reviewing them, record them (date optional per line,
    #    defaults to today; pass the message's own date when known)
    printf '198f2c1a4b5d6e7f\\t2026-08-20\\n' | \\
        python scripts/inbox_triage_ledger.py record

    # 3. drop entries too old to ever come back from the search window
    python scripts/inbox_triage_ledger.py prune

    python scripts/inbox_triage_ledger.py stats   # counts, dates, cutoff

Exit codes: 0 on success, 2 on a malformed argument/input. `filter` exits
0 whether or not anything was new -- an empty result is a normal run.
"""

import argparse
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = REPO_ROOT / "CLAUDE_INBOX_TRIAGE_SEEN.txt"

# Keep in sync with the `newer_than:` value in CLAUDE_INBOX_TRIAGE.md's
# "Dedupe protocol" step 1. Deliberately much wider than the daily run
# interval: the ledger makes re-seeing an old message nearly free, so a
# wide window costs almost nothing and is the only thing protecting
# against a late-delivered alert being missed entirely.
LOOKBACK_DAYS = 30

# Extra retention beyond the lookback window before an entry is pruned.
# See design note 3 in the module docstring -- pruning exactly at the
# window edge risks a message being re-served and re-reviewed.
RETENTION_GRACE_DAYS = 7

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_HEADER = """\
# Processed-message-ID ledger for the daily Gmail inbox-triage Routine.
# Written by scripts/inbox_triage_ledger.py -- see that file's docstring
# and CLAUDE_INBOX_TRIAGE.md's "Dedupe protocol" section. This replaces
# the `rtr-claude-processed` Gmail label, which is unavailable for good
# (the Routine holds no Gmail write scope, by Ryan's 2026-08-21 decision).
#
# One entry per line: <message-date>\\t<gmail-message-id>. Append-only in
# normal operation; only `prune` ever rewrites the file. A line whose
# first field isn't a YYYY-MM-DD date is treated as a bare, undated
# message ID: still counted as seen, never pruned.
#
# Editing by hand is fine (deleting a line makes that message eligible
# for re-review), but don't reorder or reformat wholesale -- an append
# merges cleanly across concurrent sessions and a rewrite doesn't.
"""


class LedgerError(Exception):
    """A malformed ID, date, or input line -- reported, not raised, to the caller."""


def _parse_date(value):
    if not _DATE_RE.match(value):
        raise LedgerError(f"not a YYYY-MM-DD date: {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise LedgerError(f"not a valid date: {value!r} ({exc})") from exc


def _validate_id(message_id):
    """Guard against the two mistakes that would silently corrupt the ledger:
    an empty ID, and a date pasted into the ID column (which would make the
    entry match nothing forever)."""
    if not message_id:
        raise LedgerError("empty message ID")
    if _DATE_RE.match(message_id):
        raise LedgerError(
            f"{message_id!r} looks like a date, not a message ID -- "
            "the line format is `<message-id>` or `<message-id> <YYYY-MM-DD>`"
        )
    return message_id


def read_ledger(path=LEDGER_PATH):
    """Return [(date_or_None, message_id)] in file order. Missing file -> []."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    entries = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) >= 2 and _DATE_RE.match(fields[0]):
            entries.append((_parse_date(fields[0]), fields[1]))
        else:
            # A hand-written bare ID (or anything else non-blank). Kept as
            # seen and never pruned, so a hand edit can't cause a re-review
            # loop -- see the file header.
            entries.append((None, fields[0]))
    return entries


def seen_ids(path=LEDGER_PATH):
    return {message_id for _, message_id in read_ledger(path)}


def _parse_input_lines(lines, default_date):
    """Parse stdin lines of `<message-id>` or `<message-id> <YYYY-MM-DD>`
    (either order accepted -- the Routine is an LLM and both readings are
    natural). Returns [(date, message_id)], input order, first-wins dedupe."""
    parsed = []
    already = set()
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) == 1:
            entry_date, message_id = default_date, fields[0]
        elif _DATE_RE.match(fields[0]):
            entry_date, message_id = _parse_date(fields[0]), fields[1]
        elif _DATE_RE.match(fields[1]):
            entry_date, message_id = _parse_date(fields[1]), fields[0]
        else:
            raise LedgerError(
                f"expected `<message-id>` or `<message-id> <YYYY-MM-DD>`, got: {stripped!r}"
            )
        _validate_id(message_id)
        if message_id in already:
            continue
        already.add(message_id)
        parsed.append((entry_date, message_id))
    return parsed


def _format_entry(entry_date, message_id):
    return f"{entry_date.isoformat()}\t{message_id}" if entry_date else message_id


def _write_atomic(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def append_entries(entries, path=LEDGER_PATH):
    """Append entries whose IDs aren't already in the ledger. Returns the
    list actually appended."""
    path = Path(path)
    existing = seen_ids(path)
    new = [(d, i) for d, i in entries if i not in existing]
    if not new:
        return []
    body = "".join(f"{_format_entry(d, i)}\n" for d, i in new)
    if path.exists():
        with path.open("a", encoding="utf-8") as handle:
            handle.write(body)
    else:
        _write_atomic(path, _HEADER + body)
    return new


def prune(path=LEDGER_PATH, today=None, lookback_days=LOOKBACK_DAYS):
    """Drop dated entries older than the retention cutoff, plus duplicate
    IDs (first occurrence wins). Returns (kept, dropped) entry lists."""
    today = today or date.today()
    cutoff = today - timedelta(days=lookback_days + RETENTION_GRACE_DAYS)
    kept, dropped, keep_ids = [], [], set()
    for entry_date, message_id in read_ledger(path):
        if message_id in keep_ids or (entry_date is not None and entry_date < cutoff):
            dropped.append((entry_date, message_id))
            continue
        keep_ids.add(message_id)
        kept.append((entry_date, message_id))
    if dropped:
        body = "".join(f"{_format_entry(d, i)}\n" for d, i in kept)
        _write_atomic(path, _HEADER + body)
    return kept, dropped


def _cmd_filter(args, lines):
    known = seen_ids(args.ledger)
    candidates = _parse_input_lines(lines, args.today)
    unseen = [message_id for _, message_id in candidates if message_id not in known]
    for message_id in unseen:
        print(message_id)
    print(
        f"{len(unseen)} unseen of {len(candidates)} candidate(s); "
        f"ledger holds {len(known)}",
        file=sys.stderr,
    )
    return 0


def _cmd_record(args, lines):
    entries = _parse_input_lines(lines, args.today)
    added = append_entries(entries, args.ledger)
    print(
        f"recorded {len(added)} new, skipped {len(entries) - len(added)} already-known",
        file=sys.stderr,
    )
    return 0


def _cmd_prune(args, _lines):
    kept, dropped = prune(args.ledger, today=args.today)
    print(f"pruned {len(dropped)}, kept {len(kept)}", file=sys.stderr)
    return 0


def _cmd_stats(args, _lines):
    entries = read_ledger(args.ledger)
    dated = sorted(d for d, _ in entries if d is not None)
    cutoff = args.today - timedelta(days=LOOKBACK_DAYS + RETENTION_GRACE_DAYS)
    print(f"ledger:  {args.ledger}")
    print(f"entries: {len(entries)} ({len(entries) - len(dated)} undated)")
    if dated:
        print(f"oldest:  {dated[0].isoformat()}")
        print(f"newest:  {dated[-1].isoformat()}")
    print(f"lookback window: {LOOKBACK_DAYS}d (search `newer_than:{LOOKBACK_DAYS}d`)")
    print(
        f"prune cutoff:    {cutoff.isoformat()} (window + {RETENTION_GRACE_DAYS}d grace)"
    )
    return 0


_COMMANDS = {
    "filter": _cmd_filter,
    "record": _cmd_record,
    "prune": _cmd_prune,
    "stats": _cmd_stats,
}


def main(argv=None, stdin=None):
    parser = argparse.ArgumentParser(
        description=(
            "Processed-message-ID ledger for the daily inbox-triage Routine. "
            "`filter` and `record` read message IDs on stdin, one per line."
        )
    )
    parser.add_argument("command", choices=sorted(_COMMANDS))
    parser.add_argument(
        "--ledger",
        type=Path,
        default=LEDGER_PATH,
        help="ledger file path (default: %(default)s)",
    )
    parser.add_argument(
        "--today",
        default=None,
        help="override today's date (YYYY-MM-DD); for tests and backfills",
    )
    args = parser.parse_args(argv)
    try:
        args.today = _parse_date(args.today) if args.today else date.today()
        lines = []
        if args.command in ("filter", "record"):
            lines = (stdin if stdin is not None else sys.stdin).read().splitlines()
        return _COMMANDS[args.command](args, lines)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
