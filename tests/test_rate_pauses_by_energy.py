"""Confidence bands of scripts/rate_pauses_by_energy.py (levels from a real
24-pause sample read 2026-10-10: quieter-by ranged from -2 to 23 dB)."""

from scripts.rate_pauses_by_energy import confidence_for


def test_bands():
    assert confidence_for(23.0) == "high"
    assert confidence_for(8.0) == "high"
    assert confidence_for(5.0) == "medium"
    assert confidence_for(3.0) == "medium"
    assert confidence_for(2.9) == "low"
    assert confidence_for(-2.0) == "low"
    assert confidence_for(None) == "low"
