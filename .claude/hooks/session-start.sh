#!/bin/bash
set -euo pipefail

# Only needed for Claude Code on the web -- local dev sets up its own venv
# per README's "Quick start".
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Async: let the session open immediately: installs finish in the
# background instead of blocking session start (trade-off: python/pip/
# pytest/ruff -- and PATH itself, via CLAUDE_ENV_FILE below -- aren't
# ready until this finishes, up to asyncTimeout ms later).
echo '{"async": true, "asyncTimeout": 300000}'

cd "$CLAUDE_PROJECT_DIR"

# The container's system Python has an old Debian-packaged setuptools that
# fails building legacy setup.py-based deps (langdetect, wordninja) and is
# externally-managed besides. A venv sidesteps both -- same approach
# README's own "Quick start" uses for local dev.
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip

# Mirrors .github/workflows/test.yml: root requirements.txt is a superset
# covering app/, archive/, and worker/'s needs for the hermetic pytest
# suite (no network/Postgres/playwright-install required -- see README's
# "Running tests").
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# shared_static/deep_link.js's JS suite (tests_js/).
npm install

# Persist the venv on PATH so plain `python`/`pip`/`pytest`/`ruff` calls in
# the session use it without manual activation.
echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
echo "export VIRTUAL_ENV=\"$CLAUDE_PROJECT_DIR/.venv\"" >> "$CLAUDE_ENV_FILE"
