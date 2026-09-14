#!/usr/bin/env python3
"""WO-352: confirms `ARCHIVE_INGEST_TOKEN`/`ARCHIVE_BASE_URL` are loaded
from the shared checkout's `.env` -- never prints the token itself, only
`bool(...)`. A worktree has no `.env` of its own (`load_dotenv()` with no
path walks up from cwd and finds nothing useful there), so this always
loads the shared checkout's file by explicit path first, per CLAUDE.md's
"Archive tokens in a worktree" bullet.

Usage:
    .venv/bin/python scripts/wo352_check_env.py
"""

import os

import dotenv

dotenv.load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")
print("ARCHIVE_INGEST_TOKEN set:", bool(os.environ.get("ARCHIVE_INGEST_TOKEN")))
print("ARCHIVE_BASE_URL:", os.environ.get("ARCHIVE_BASE_URL"))
