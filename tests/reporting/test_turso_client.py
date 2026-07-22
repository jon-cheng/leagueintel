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


# ── log_question ─────────────────────────────────────────────────────────────


def test_log_question_executes_insert_and_commits():
    mock_conn = MagicMock()

    with patch.object(turso_client, "get_ops_connection", return_value=mock_conn):
        turso_client.log_question(
            tool_used="run_analysis",
            analysis_used="draft_roi",
            tokens_input=1820,
            tokens_output=450,
            cache_write_tokens=900,
            cache_read_tokens=300,
        )

    args, _ = mock_conn.execute.call_args
    sql, params = args
    assert "INSERT INTO chat_log" in sql
    assert params == ("run_analysis", "draft_roi", 1820, 450, 900, 300)
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


def test_log_question_defaults_cache_tokens_to_zero():
    mock_conn = MagicMock()

    with patch.object(turso_client, "get_ops_connection", return_value=mock_conn):
        turso_client.log_question(
            tool_used="query_db",
            analysis_used=None,
            tokens_input=100,
            tokens_output=50,
        )

    _, params = mock_conn.execute.call_args[0]
    assert params[-2:] == (0, 0)


def test_log_question_failure_does_not_raise():
    with patch.object(
        turso_client, "get_ops_connection", side_effect=ConnectionError("down")
    ):
        # should swallow the error and simply log a warning
        turso_client.log_question(
            tool_used=None,
            analysis_used=None,
            tokens_input=100,
            tokens_output=50,
        )


# ── get_usage_report ─────────────────────────────────────────────────────────


def test_get_usage_report_returns_rows():
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        ("2026-07-13", 3, 1500, 400, 900, 300, 0.0195),
        ("2026-07-12", 1, 800, 200, 0, 0, 0.0104),
    ]

    with patch.object(turso_client, "get_ops_connection", return_value=mock_conn):
        result = turso_client.get_usage_report()

    assert result == [
        ("2026-07-13", 3, 1500, 400, 900, 300, 0.0195),
        ("2026-07-12", 1, 800, 200, 0, 0, 0.0104),
    ]
    mock_conn.close.assert_called_once()


def test_get_usage_report_propagates_connection_failure():
    with patch.object(
        turso_client, "get_ops_connection", side_effect=ConnectionError("down")
    ):
        # unlike get_today_usage, this should raise rather than swallow —
        # it's a manually-run dev tool, not on the chatbot's critical path
        try:
            turso_client.get_usage_report()
            assert False, "expected ConnectionError to propagate"
        except ConnectionError:
            pass


# ── get_question_cost_report ─────────────────────────────────────────────────


def test_get_question_cost_report_returns_rows():
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        (2, "2026-07-13 10:05:00", "run_analysis", "draft_roi", 1500, 400, 900, 300, 0.0195),
        (1, "2026-07-13 10:00:00", "query_db", None, 800, 200, 0, 0, 0.0104),
    ]

    with patch.object(turso_client, "get_ops_connection", return_value=mock_conn):
        result = turso_client.get_question_cost_report()

    assert result == [
        (2, "2026-07-13 10:05:00", "run_analysis", "draft_roi", 1500, 400, 900, 300, 0.0195),
        (1, "2026-07-13 10:00:00", "query_db", None, 800, 200, 0, 0, 0.0104),
    ]
    mock_conn.close.assert_called_once()


def test_get_question_cost_report_propagates_connection_failure():
    with patch.object(
        turso_client, "get_ops_connection", side_effect=ConnectionError("down")
    ):
        # same as get_usage_report — a manually-run dev tool, so a raised
        # exception here is more useful than a silently empty report
        try:
            turso_client.get_question_cost_report()
            assert False, "expected ConnectionError to propagate"
        except ConnectionError:
            pass


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
