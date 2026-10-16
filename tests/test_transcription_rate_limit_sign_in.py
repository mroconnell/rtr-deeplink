"""The transcription rate-limit message (HTTP 429 from
/api/transcription/check-feasibility) offers signed-out visitors a plain
link to /sign-in, since signed-in visitors are exempt from the limit.

Both copies of runFeasibilityCheck() are checked: app/static/player.js
(resolver) and archive/static/meeting_page.js (Archive). The 429 branch
is cut out of each file and run under node against a tiny stub DOM, so
the test exercises the real code, not a copy of it.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = ["app/static/player.js", "archive/static/meeting_page.js"]

_HARNESS = r"""
const marked = [];
window = { rtrMarkSignInReturn: () => marked.push(true) };
class El {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener(type, fn) { this.listeners[type] = fn; }
}
document = { createElement: (tag) => new El(tag) };
const checkStatusEl = new El('p');
BRANCH
const link = checkStatusEl.children.find((c) => c instanceof El);
link.listeners.click();
console.log(JSON.stringify({
  text: checkStatusEl.textContent,
  tail: checkStatusEl.children.filter((c) => typeof c === 'string'),
  tag: link.tag, href: link.href, label: link.textContent,
  cls: checkStatusEl.className, marked: marked.length,
}));
"""


def _rate_limit_branch(source: str) -> str:
    match = re.search(
        r"if \(res\.status === 429\) \{\n(.*?)\n\s*\} else if \(data\.ok\)",
        source,
        re.S,
    )
    assert match, "429 branch not found"
    return match.group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("path", FILES)
def test_rate_limit_message_links_to_sign_in(path):
    branch = _rate_limit_branch((ROOT / path).read_text())
    script = _HARNESS.replace("BRANCH", branch)
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    ).stdout
    result = json.loads(out)
    assert "try again in about an hour" in result["text"]
    assert result["tag"] == "a"
    assert result["href"] == "/sign-in"
    assert result["label"] == "sign in"
    assert result["tail"] == [" to request without the limit."]
    assert result["cls"] == "transcribe-status error"
    # Clicking stashes the return URL so sign-in comes back to this page.
    assert result["marked"] == 1
