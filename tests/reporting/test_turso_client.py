# tests/reporting/test_turso_client.py
"""
Tests for the Turso ops-DB client used for chatbot usage tracking.

libsql_experimental.connect is mocked throughout — these tests never
touch a real Turso database. What they protect:
- the SQL/upsert logic is wired correctly against a fake connection
- every function degrades to a safe default (never raises) when the
  Turso call fails, since usage tracking must never block the chatbot
"""

from unittest.mock import MagicMock, patch

import leagueintel.reporting.turso_client as turso_client


# ── get_today_usage ──────────────────────────────────────────────────────────


def test_get_today_usage_returns_row():
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (1000, 500, 2)

    with patch.object(turso_client, "get_ops_connection", return_value=mock_conn):
        result = turso_client.get_today_usage()

    assert result == (1000, 500, 2)
    mock_conn.close.assert_called_once()


def test_get_today_usage_no_row_for_today():
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    with patch.object(turso_client, "get_ops_connection", return_value=mock_conn):
        result = turso_client.get_today_usage()

    assert result == (0, 0, 0)


def test_get_today_usage_connection_failure_returns_zeros():
    with patch.object(
        turso_client, "get_ops_connection", side_effect=ConnectionError("down")
    ):
        result = turso_client.get_today_usage()

    assert result == (0, 0, 0)


# ── record_usage ──────────────────────────────────────────────────────────────


def test_record_usage_executes_upsert_and_commits():
    mock_conn = MagicMock()

    with patch.object(turso_client, "get_ops_connection", return_value=mock_conn):
        turso_client.record_usage(1820, 450)

    args, _ = mock_conn.execute.call_args
    sql, params = args
    assert "INSERT INTO usage" in sql
    assert "ON CONFLICT" in sql
    assert params[1:] == (1820, 450)
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


def test_record_usage_failure_does_not_raise():
    with patch.object(
        turso_client, "get_ops_connection", side_effect=ConnectionError("down")
    ):
        # should swallow the error and simply log a warning
        turso_client.record_usage(100, 50)


# ── check_daily_budget ────────────────────────────────────────────────────────


def test_check_daily_budget_within_limit():
    with patch.object(turso_client, "get_today_usage", return_value=(1000, 200, 1)):
        with patch("leagueintel.config.CHATBOT_DAILY_TOKEN_LIMIT", 100000):
            within_budget, tokens_used = turso_client.check_daily_budget()

    assert within_budget is True
    assert tokens_used == 1200


def test_check_daily_budget_exceeded():
    with patch.object(turso_client, "get_today_usage", return_value=(90000, 20000, 5)):
        with patch("leagueintel.config.CHATBOT_DAILY_TOKEN_LIMIT", 100000):
            within_budget, tokens_used = turso_client.check_daily_budget()

    assert within_budget is False
    assert tokens_used == 110000


def test_check_daily_budget_exactly_at_limit_is_not_within_budget():
    with patch.object(turso_client, "get_today_usage", return_value=(50000, 50000, 1)):
        with patch("leagueintel.config.CHATBOT_DAILY_TOKEN_LIMIT", 100000):
            within_budget, _ = turso_client.check_daily_budget()

    assert within_budget is False  # strictly < limit, not <=
