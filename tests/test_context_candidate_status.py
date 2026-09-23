"""Synthetic boolean branch tests for the approved candidate truth table."""

import pytest

from archive.context.status import NEXT_ACTION_LABELS, next_action_for


@pytest.mark.parametrize(
    "facts, expected",
    [
        ({}, "resolve_needed"),
        ({"meeting_identified": True}, "recording_needed"),
        ({"recording_identified": True}, "ingest_needed"),
        ({"matched": True}, "moment_needed"),
        ({"unresolved": True, "matched": True}, "resolve_needed"),
        ({"conflict": True, "unresolved": True, "matched": True}, "conflict"),
        ({"failed": True, "conflict": True, "matched": True}, "check_failed"),
    ],
)
def test_state_precedence(facts, expected):
    assert next_action_for(**facts) == expected


def test_labels_have_only_milestone_one_states():
    assert set(NEXT_ACTION_LABELS) == {
        "new",
        "check_failed",
        "conflict",
        "resolve_needed",
        "recording_needed",
        "ingest_needed",
        "moment_needed",
    }
