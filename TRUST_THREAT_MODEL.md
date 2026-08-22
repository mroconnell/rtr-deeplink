# Fake/spoofed "government" content — threat model

Threat-modeled 2026-08-10, kept current as mitigations ship. This
is a real, currently wide-open gap, not a hypothetical: nothing
verifies that a submitted URL's site is a genuine government body.

Two mitigations are built (see `BACKLOG_DONE.md`); the rest are
unsequenced, per Ryan's own framing ("at some point"). One decision
made deliberately *against* a mitigation — not widening `noindex` /
the sitemap filter to cover `best_effort` — lives in `BACKLOG.md`'s
**Standing decisions**, and should be read before proposing it again.

Split out of [BACKLOG.md](BACKLOG.md) 2026-08-22; that file keeps a
short stub entry pointing here. Update both together.

---

**Fake/spoofed "government" pages and non-government
content getting archived as if official: a real, currently wide-open
gap.** Nothing verifies a submitted URL's site is a genuine government
body. Platform detection is pure URL-shape matching, and
jurisdiction/title/date are extracted from the submitted page's own
content with zero cross-check against any independent registry —
anyone could claim any jurisdiction name. `generic_fallback.py` (built
to catch anything unmatched) is the widest-open path — no domain
restriction at all, and a naive TLD allowlist would break most of what
currently works, since most real supported platforms aren't `.gov`
domains themselves.

**Real consequences if exploited**: fabricated "official" content
published as a seemingly-legitimate, SEO-indexed page under a
real-sounding jurisdiction name; a real official's words fabricated or
altered under the appearance of an authoritative civic record; the
Archive used as free SEO-boosted hosting for spam/harassment; broader
reputational/trust erosion. The "Report a problem" flow
(`ProblemReport`) already gives a reactive, after-publication path to
flag a suspicious page.

**Mitigations, first two built (2026-08-11 and 2026-08-21, see
`BACKLOG_DONE.md`), rest not decided**: `noindex` on `generic_fallback`/
`unknown`-platform pages by default (shipped 2026-08-11 — deliberately
**not** widened to cover the more common YouTube-delegated
`best_effort` fallback path, see **Standing decisions**); social
auto-posting refuses anything carrying `best_effort` or
`platform == "unknown"` (shipped 2026-08-21, WO-21); manual review
before a brand-new jurisdiction goes live (partially approached from
the other side by the low-trust review queue — a genuine
*pre*-publication hold is still unbuilt); platform-based trust tiers
instead of domain allowlisting (named-vendor adapters target products
sold specifically to local governments — real if imperfect signal);
a curated known-jurisdiction list grown over time (ties naturally into
the coverage page, which could double as its public face). Not
prioritized/sequenced — per the user's own framing ("at some point").
