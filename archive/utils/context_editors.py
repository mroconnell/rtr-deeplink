"""Who is allowed to write a `/context` feed entry (WO-942).

This is the first place in this repo that gates a signed-in visitor's
*capability* rather than just their own account's data -- everywhere else
Clerk touches (SavedItem, /account/*) a signed-in user only ever reads or
writes their own rows, so "is this the right person" was always answered
by comparing `clerk_user_id` to the row's own owner. Editing the context
feed needs a real yes/no role check instead: most signed-in visitors must
NOT get a form that writes public content.

**Why an env var instead of a database table.** There is exactly one real
editor today (Ryan). A `roles` table, an admin UI to manage it, and the
migration all cost real effort for a role that has never had a second
member -- `CONTEXT_EDITOR_CLERK_IDS` is the entire mechanism, a
comma-separated list of Clerk user ids, until there's a second editor to
actually justify it. Deliberately lives only in the Archive's own env
(not shared with the resolver, which never needs to know) -- same
service-boundary reasoning as everywhere else editorial/admin state lives
in this app.

**The failure mode to know about.** This fails *closed*, silently: an
unset or empty env var, or an id that doesn't match, both just mean "not
an editor" -- no error, no log line, the context-editing routes 404 the
same way they would for any other visitor. That silence is exactly what
makes a wrong value dangerous rather than merely broken: pasting a Clerk
*development*-instance user id (see CLAUDE.md's "Clerk production
cutover" entry on how easy that mix-up is) into this var in production
gives no error at all -- the form just never appears for anyone, and
nothing short of someone actually trying it would reveal the mistake.
Double-check the id came from the production Clerk instance, not a dev
one, before setting this.
"""

import os
from typing import Optional


def is_context_editor(clerk_user_id: Optional[str]) -> bool:
    """True only if `clerk_user_id` is a non-empty id present in the
    (comma-separated, whitespace-tolerant) `CONTEXT_EDITOR_CLERK_IDS` env
    var. Reads the env on every call, deliberately, rather than caching it
    at import time -- so a test can `monkeypatch.setenv(...)` per case,
    and so a real deploy that changes the var takes effect on the next
    request with no restart. Fails closed: an unset/empty var, or a
    `None`/empty id, both return False.
    """
    if not clerk_user_id:
        return False
    raw = os.environ.get("CONTEXT_EDITOR_CLERK_IDS", "")
    editor_ids = {piece.strip() for piece in raw.split(",") if piece.strip()}
    return clerk_user_id in editor_ids
