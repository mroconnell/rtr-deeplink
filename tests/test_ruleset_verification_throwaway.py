"""Throwaway test to verify the branch protection ruleset actually blocks
merging on a failing `test` status check. Deleted before this PR merges
(the PR itself is never merged -- see ruleset verification in chat)."""


def test_deliberately_fails_for_ruleset_verification():
    assert False, "intentional failure to verify branch ruleset blocks merge"
