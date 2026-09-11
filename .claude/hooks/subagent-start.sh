#!/bin/bash
# SubagentStart hook: give every subagent its own scratch directory.
#
# Why: the harness hands every subagent spawned from one session the SAME
# "Scratchpad directory" as the parent (same session id, same path), so two
# parallel agents that both write e.g. pr_body.md overwrite each other.
# Real incident 2026-09-10 (WO-179 vs WO-175, PR #909 went up with the
# wrong description). See CLAUDE.md's multi-session bullet.
#
# What: read the hook's stdin JSON, create
#   <scratchpad_dir>/agents/<agent_id>/
# and hand that path back to the subagent as additionalContext so it uses
# it instead of the shared root. Exits 0 and does nothing if the fields
# are missing, so it can never block an agent from starting.
set -u

input="$(cat)"

python3 - "$input" <<'PY'
import json, os, sys

try:
    data = json.loads(sys.argv[1] or "{}")
except json.JSONDecodeError:
    sys.exit(0)

root = data.get("scratchpad_dir") or ""
agent_id = data.get("agent_id") or ""
if not root or not agent_id:
    sys.exit(0)

# agent_id is harness-generated hex; keep only safe chars regardless.
safe_id = "".join(ch for ch in agent_id if ch.isalnum() or ch in "-_")
private = os.path.join(root, "agents", safe_id)
try:
    os.makedirs(private, exist_ok=True)
except OSError:
    sys.exit(0)

context = (
    f"Your private scratch directory is {private} (already created). "
    f"The session scratchpad {root} is SHARED with the parent session and "
    "every other subagent it spawns, so a file written there under a generic "
    "name (pr_body.md, commit_msg.txt, report.csv) can be overwritten by "
    "another agent before you read it back. Write ALL temporary files -- PR "
    "bodies, commit messages, scripts, outputs -- under your private directory, "
    "never at the shared root. If you must pass a file to gh pr create "
    "--body-file or git commit -F, put it in your private directory."
)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SubagentStart",
        "additionalContext": context,
    }
}))
PY
exit 0
