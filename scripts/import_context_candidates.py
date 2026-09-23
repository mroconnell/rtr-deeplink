#!/usr/bin/env python3
"""Preview or apply a bounded CSV/JSON Context research import.

The file must either use the canonical field names accepted by
``archive.context.importer.normalize_row`` or supply an explicit mapping from
canonical name to source header. The mapping can be repeated on the command
line (``--map social_url='Reel URL'``) or loaded from a JSON object with
``--map-file``. Unmapped source columns remain intact in each observation's raw
payload; they do not become lookup claims.

Preview is the default. ``--apply`` is required to write. Both modes call the
token-gated Archive endpoint and require explicit ARCHIVE_BASE_URL and
ARCHIVE_INGEST_TOKEN environment variables.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archive.context.importer import CANONICAL_FIELDS  # noqa: E402
from archive.context.schemas import MAX_IMPORT_ROWS  # noqa: E402

_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 30


def _parse_mapping(items: list[str], mapping_file: Path | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if mapping_file is not None:
        try:
            loaded = json.loads(mapping_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read mapping file: {exc}") from exc
        if not isinstance(loaded, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in loaded.items()
        ):
            raise ValueError("The mapping file must be a JSON object of text values.")
        mapping.update(loaded)
    for item in items:
        canonical, separator, source = item.partition("=")
        if not separator or not canonical.strip() or not source.strip():
            raise ValueError(f"Invalid --map {item!r}; use canonical=source_header.")
        mapping[canonical.strip()] = source.strip()
    unknown = set(mapping) - CANONICAL_FIELDS
    if unknown:
        raise ValueError(
            "Unknown canonical mapping field(s): " + ", ".join(sorted(unknown))
        )
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Each source header may map to only one canonical field.")
    return mapping


def _read_input(path: Path) -> list[dict[str, Any]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Could not inspect input file: {exc}") from exc
    if size > _MAX_FILE_BYTES:
        raise ValueError(f"Input exceeds the {_MAX_FILE_BYTES}-byte limit.")
    try:
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
        elif path.suffix.lower() == ".json":
            loaded = json.loads(path.read_text(encoding="utf-8"))
            rows = loaded.get("rows") if isinstance(loaded, dict) else loaded
            if not isinstance(rows, list):
                raise ValueError(
                    "JSON input must be a list or an object with a rows list."
                )
        else:
            raise ValueError("Input must be a .csv or .json file.")
    except (OSError, csv.Error, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read input file: {exc}") from exc
    if not rows or len(rows) > MAX_IMPORT_ROWS:
        raise ValueError(
            f"Input must contain between 1 and {MAX_IMPORT_ROWS} rows; got {len(rows)}."
        )
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Every input row must be an object.")
    return rows


def _map_rows(
    source_rows: list[dict[str, Any]], mapping: dict[str, str]
) -> list[dict[str, Any]]:
    if not mapping:
        unknown = set().union(*(set(row) for row in source_rows)) - CANONICAL_FIELDS
        if unknown:
            raise ValueError(
                "Input has non-canonical fields; map them explicitly. Unknown: "
                + ", ".join(sorted(str(field) for field in unknown))
            )
        return source_rows
    missing_headers = {
        source_header
        for source_header in mapping.values()
        if all(source_header not in row for row in source_rows)
    }
    if missing_headers:
        raise ValueError(
            "Mapped source header(s) not found: " + ", ".join(sorted(missing_headers))
        )
    return [
        {
            **{
                canonical: row.get(source_header)
                for canonical, source_header in mapping.items()
            },
            "__raw_payload__": row,
        }
        for row in source_rows
    ]


def _post_import(base_url: str, token: str, payload: dict[str, Any]) -> dict:
    url = f"{base_url.rstrip('/')}/internal/context/candidates/import"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"Archive returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Archive request failed: {exc.reason}") from exc
    if len(body) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("Archive response exceeded the 2 MiB limit.")
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Archive returned a non-JSON response.") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Archive returned an unexpected response shape.")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", type=Path, help="A CSV or JSON input file")
    parser.add_argument("--provider", required=True, help="Research provider name")
    parser.add_argument("--source-location", help="Optional source sheet/file location")
    parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="CANONICAL=SOURCE",
        help="Map a canonical field to a source header (repeatable)",
    )
    parser.add_argument("--map-file", type=Path, help="JSON header mapping object")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply", action="store_true", help="Write observations (default: preview)"
    )
    mode.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="Preview only (the default; accepted for explicit operator commands)",
    )
    parser.set_defaults(apply=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_url = os.environ.get("ARCHIVE_BASE_URL", "").strip()
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "").strip()
    if not base_url.startswith(("http://", "https://")):
        print(
            "ARCHIVE_BASE_URL must be explicitly set to an http(s) URL.",
            file=sys.stderr,
        )
        return 2
    if not token:
        print("ARCHIVE_INGEST_TOKEN must be explicitly set.", file=sys.stderr)
        return 2
    try:
        mapping = _parse_mapping(args.map, args.map_file)
        rows = _map_rows(_read_input(args.input), mapping)
        result = _post_import(
            base_url,
            token,
            {
                "schema_version": 1,
                "provider": args.provider,
                "source_location": args.source_location,
                "rows": rows,
                "apply": args.apply,
            },
        )
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 1 if result.get("rejected_rows") or result.get("error_rows") else 0


if __name__ == "__main__":
    raise SystemExit(main())
