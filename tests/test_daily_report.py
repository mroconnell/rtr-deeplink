"""Tests for app/reporting.py's pure logic: email composition and the
Resend list-endpoint pagination/24h-window filtering, plus GET
/admin/daily-report's token gating. Everything else (Clerk API calls, the
actual send, the DB count) is a thin wrapper around a live call and is
exercised via scripts/daily_report.py --dry-run instead (see that
script's own docstring) rather than unit-tested here.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.main
import app.reporting as reporting_module
from aiohttp_mock import FakeResponse, mock_session
from app.reporting import MetricResult, _count_since, compose_report_email

resolver_client = TestClient(app.main.app)


def _metrics(**overrides):
    base = {
        "clerk_total_users": MetricResult(142),
        "clerk_new_users_24h": MetricResult(1),
        "resend_sent_24h": MetricResult(8),
        "resend_new_subscribers_24h": MetricResult(0),
        "reports_run": MetricResult(6),
    }
    base.update(overrides)
    return base


def test_compose_report_email_all_success():
    subject, body = compose_report_email(_metrics(), report_date=date(2026, 8, 11))

    assert subject == "Daily report 2026-08-11: 6 reports run, 1 new users"
    assert "Total: 142" in body
    assert "New in last 24h: 1" in body
    assert "Emails sent in last 24h: 8" in body
    assert "New subscribers in last 24h: 0" in body
    assert "Resolve attempts in last 24h: 6" in body


def test_compose_report_email_reports_partial_failure_inline():
    metrics = _metrics(resend_sent_24h=MetricResult(None, "RuntimeError: timed out"))
    subject, body = compose_report_email(metrics, report_date=date(2026, 8, 11))

    # A failed metric shouldn't blank out the rest of the email.
    assert "Total: 142" in body
    assert "Resolve attempts in last 24h: 6" in body
    assert "Emails sent in last 24h: unavailable (RuntimeError: timed out)" in body


async def test_count_since_single_page_filters_by_cutoff():
    cutoff = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    recent = (cutoff + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    old = (cutoff - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    routes = {
        "https://api.resend.com/emails?limit=100": FakeResponse(
            text=(
                '{"data": ['
                f'{{"id": "1", "created_at": "{recent}"}},'
                f'{{"id": "2", "created_at": "{old}"}}'
                '], "has_more": false}'
            )
        ),
    }
    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            count = await _count_since(session, "https://api.resend.com/emails", "test-key", cutoff)

    assert count == 1


async def test_count_since_stops_paging_once_past_cutoff():
    cutoff = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    recent = (cutoff + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    also_recent = (cutoff + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    old = (cutoff - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    routes = {
        "https://api.resend.com/emails?limit=100": FakeResponse(
            text=f'{{"data": [{{"id": "1", "created_at": "{recent}"}}], "has_more": true}}'
        ),
        "https://api.resend.com/emails?limit=100&after=1": FakeResponse(
            text=(
                '{"data": ['
                f'{{"id": "2", "created_at": "{also_recent}"}},'
                f'{{"id": "3", "created_at": "{old}"}}'
                '], "has_more": true}'
            )
        ),
        # Should never be requested: page 2 already hit an item older than
        # cutoff, so paging must stop there rather than walking further.
    }
    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            count = await _count_since(session, "https://api.resend.com/emails", "test-key", cutoff)

    assert count == 2


def test_admin_daily_report_requires_token():
    # Same 404-not-401 gating every other /admin/* route uses -- see
    # tests/test_404_handling.py's matching test for /admin/stats.
    response = resolver_client.get("/admin/daily-report")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_admin_daily_report_dry_run_returns_composed_email_without_sending(monkeypatch):
    async def fake_gather_metrics():
        return _metrics()

    monkeypatch.setattr(reporting_module, "gather_metrics", fake_gather_metrics)

    response = resolver_client.get(
        "/admin/daily-report", params={"token": "test-admin-token", "dry_run": "true"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sent"] is False
    assert "6 reports run" in body["subject"]
    assert "Total: 142" in body["body"]
