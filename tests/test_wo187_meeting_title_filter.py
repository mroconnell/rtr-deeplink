"""WO-187 (2026-09-11): a real title got past both `_looks_like_real_
meeting()`'s checks in `scripts/wo134_confirmed_hits_ingest.py` and was
ingested live before being caught by hand.

Capitol Heights, MD's own YouTube channel titled a real clip "Council
Member Victor James Sr interview for N'style back to school block
party" -- a promotional interview, not a meeting recording. The word
"Council" alone satisfies `MEETING_ALLOWLIST`, and nothing in
`PROMO_BLOCKLIST` caught "interview" as a non-meeting signal. Fixed by
adding "interview" to `PROMO_BLOCKLIST`; this test is the regression
case, following this repo's convention of adding a fixture-backed test
for any bug found via live testing. See `BACKLOG_DONE.md`'s WO-187
entry for the live page this produced (flagged for deletion, not
auto-deleted) and `docs/COVERAGE_HANDOVER.md`/`CLAUDE.md` for why a
real title, not a synthetic one, is used here.

Note: `scripts/adhoc_civicplus_pipeline.py` has its own separate,
unshared copy of `PROMO_BLOCKLIST`/`_looks_like_real_meeting()` (see
that module's own comment referencing a third copy in
`scripts/nationwide_2404_ingest.py`) -- this fix only touches the one
copy the WO-187 sweep actually used
(`wo134_confirmed_hits_ingest.py`'s), consistent with WO-187's own
scope. Unifying the three copies is a separate, larger cleanup, not
done here.
"""

from scripts.wo134_confirmed_hits_ingest import _looks_like_real_meeting


def test_council_member_interview_is_not_a_meeting():
    title = "Council Member Victor James Sr interview for N'style back to school block party"
    assert _looks_like_real_meeting(title) is False


def test_ordinary_council_meeting_title_still_passes():
    assert _looks_like_real_meeting("City Council Meeting, September 9, 2026") is True
