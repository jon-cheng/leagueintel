# tests/reporting/test_chatbot_throttling.py
"""
Tests for chatbot daily token budget throttling.
Uses a temporary in-memory SQLite DB to avoid touching real data.
"""

import sqlite3
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary SQLite DB with the usage table."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE usage (
            date TEXT NOT NULL,
            tokens_input INTEGER DEFAULT 0,
            tokens_output INTEGER DEFAULT 0,
            question_count INTEGER DEFAULT 0,
            PRIMARY KEY (date)
        )
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def patch_db_path(temp_db):
    """Patch DEFAULT_DB_PATH to point to the temp DB."""
    with patch("leagueintel.reporting.chatbot.DEFAULT_DB_PATH", temp_db):
        with patch("leagueintel.storage.database.DEFAULT_DB_PATH", temp_db):
            yield temp_db


# ── _get_today_usage ──────────────────────────────────────────────────────────


def test_get_today_usage_empty_db(patch_db_path):
    """Returns zeros when no usage recorded yet."""
    from leagueintel.reporting.chatbot import _get_today_usage

    tokens_in, tokens_out, questions = _get_today_usage()
    assert tokens_in == 0
    assert tokens_out == 0
    assert questions == 0


def test_get_today_usage_after_recording(patch_db_path):
    """Returns correct values after recording usage."""
    from leagueintel.reporting.chatbot import _get_today_usage, _record_usage

    _record_usage(1000, 500)
    tokens_in, tokens_out, questions = _get_today_usage()
    assert tokens_in == 1000
    assert tokens_out == 500
    assert questions == 1


# ── _record_usage ─────────────────────────────────────────────────────────────


def test_record_usage_first_question(patch_db_path):
    """First question of the day inserts a new row."""
    from leagueintel.reporting.chatbot import _record_usage, _get_today_usage

    _record_usage(1820, 450)
    tokens_in, tokens_out, questions = _get_today_usage()
    assert tokens_in == 1820
    assert tokens_out == 450
    assert questions == 1


def test_record_usage_accumulates(patch_db_path):
    """Multiple questions accumulate correctly."""
    from leagueintel.reporting.chatbot import _record_usage, _get_today_usage

    _record_usage(1000, 200)
    _record_usage(1500, 300)
    _record_usage(800, 150)
    tokens_in, tokens_out, questions = _get_today_usage()
    assert tokens_in == 3300
    assert tokens_out == 650
    assert questions == 3


# ── check_daily_budget ────────────────────────────────────────────────────────


def test_budget_within_limit(patch_db_path):
    """Returns True when under the daily limit."""
    from leagueintel.reporting.chatbot import _record_usage, check_daily_budget

    _record_usage(1000, 200)  # 1,200 total — well under 100,000
    within_budget, tokens_used = check_daily_budget()
    assert within_budget is True
    assert tokens_used == 1200


def test_budget_exceeded(patch_db_path):
    """Returns False when over the daily limit."""
    from leagueintel.reporting.chatbot import _record_usage, check_daily_budget

    _record_usage(90000, 20000)  # 110,000 total — over 100,000
    within_budget, tokens_used = check_daily_budget()
    assert within_budget is False
    assert tokens_used == 110000


def test_budget_exactly_at_limit(patch_db_path):
    """At exactly the limit — still within budget (strict less than)."""
    from leagueintel.reporting.chatbot import _record_usage, check_daily_budget

    with patch("leagueintel.reporting.chatbot.CHATBOT_DAILY_TOKEN_LIMIT", 100000):
        _record_usage(50000, 50000)  # exactly 100,000
        within_budget, _ = check_daily_budget()
        assert within_budget is False  # < not <=


def test_budget_custom_limit(patch_db_path):
    """Custom limit from config is respected."""
    from leagueintel.reporting.chatbot import _record_usage, check_daily_budget

    with patch("leagueintel.reporting.chatbot.CHATBOT_DAILY_TOKEN_LIMIT", 5000):
        _record_usage(3000, 1000)  # 4,000 — under 5,000
        within_budget, _ = check_daily_budget()
        assert within_budget is True

        _record_usage(1000, 500)  # now 5,500 — over 5,000
        within_budget, _ = check_daily_budget()
        assert within_budget is False


# ── ask() integration ─────────────────────────────────────────────────────────


def test_ask_blocked_when_over_budget(patch_db_path):
    """ask() returns budget message without calling API when over limit."""
    from leagueintel.reporting.chatbot import _record_usage, ask

    # exhaust the budget
    with patch("leagueintel.reporting.chatbot.CHATBOT_DAILY_TOKEN_LIMIT", 100):
        _record_usage(50, 60)  # 110 total — over 100

        # patch the API client so we can verify it's never called
        with patch("leagueintel.reporting.chatbot.client") as mock_client:
            text, fig = ask("Who had the best waiver pickup in 2025?")

            # API should never have been called
            mock_client.messages.create.assert_not_called()

            # response should be the budget message
            assert "limit" in text.lower()
            assert fig is None
