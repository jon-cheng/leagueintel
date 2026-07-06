# tests/reporting/test_chatbot_throttling.py
"""
Tests for chatbot daily token budget throttling.
Uses a temporary SQLite DB to avoid touching real data.

Both _get_today_usage and _record_usage now use DEFAULT_DB_PATH
directly from the chatbot module — so a single patch of
leagueintel.reporting.chatbot.DEFAULT_DB_PATH is sufficient.
"""

import sqlite3
import pytest
from datetime import date
from unittest.mock import patch
from pathlib import Path
import leagueintel.reporting.chatbot as chatbot_module


# ── helpers ───────────────────────────────────────────────────────────────────

def make_usage_db(path: Path) -> None:
    conn = sqlite3.connect(path)
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


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_db(tmp_path):
    """
    Redirect all DB operations to a temp DB for every test.
    autouse=True means every test gets this automatically.
    Both _get_today_usage and _record_usage read DEFAULT_DB_PATH
    from the chatbot module — patch it once here.
    """
    db_path = tmp_path / "test.db"
    make_usage_db(db_path)

    original = chatbot_module.DEFAULT_DB_PATH
    chatbot_module.DEFAULT_DB_PATH = db_path
    yield db_path
    chatbot_module.DEFAULT_DB_PATH = original


@pytest.fixture(autouse=True)
def reset_limit():
    """Restore CHATBOT_DAILY_TOKEN_LIMIT after each test."""
    original = chatbot_module.CHATBOT_DAILY_TOKEN_LIMIT
    yield
    chatbot_module.CHATBOT_DAILY_TOKEN_LIMIT = original


# ── _get_today_usage ──────────────────────────────────────────────────────────

def test_get_today_usage_empty_db():
    tokens_in, tokens_out, questions = chatbot_module._get_today_usage()
    assert tokens_in == 0
    assert tokens_out == 0
    assert questions == 0


def test_get_today_usage_after_recording():
    chatbot_module._record_usage(1000, 500)
    tokens_in, tokens_out, questions = chatbot_module._get_today_usage()
    assert tokens_in == 1000
    assert tokens_out == 500
    assert questions == 1


# ── _record_usage ─────────────────────────────────────────────────────────────

def test_record_usage_first_question():
    chatbot_module._record_usage(1820, 450)
    tokens_in, tokens_out, questions = chatbot_module._get_today_usage()
    assert tokens_in == 1820
    assert tokens_out == 450
    assert questions == 1


def test_record_usage_accumulates():
    chatbot_module._record_usage(1000, 200)
    chatbot_module._record_usage(1500, 300)
    chatbot_module._record_usage(800, 150)
    tokens_in, tokens_out, questions = chatbot_module._get_today_usage()
    assert tokens_in == 3300
    assert tokens_out == 650
    assert questions == 3


# ── check_daily_budget ────────────────────────────────────────────────────────

def test_budget_within_limit():
    chatbot_module.CHATBOT_DAILY_TOKEN_LIMIT = 100000
    chatbot_module._record_usage(1000, 200)  # 1,200 total
    within_budget, tokens_used = chatbot_module.check_daily_budget()
    assert within_budget is True
    assert tokens_used == 1200


def test_budget_exceeded():
    chatbot_module.CHATBOT_DAILY_TOKEN_LIMIT = 100000
    chatbot_module._record_usage(90000, 20000)  # 110,000 total
    within_budget, tokens_used = chatbot_module.check_daily_budget()
    assert within_budget is False
    assert tokens_used == 110000


def test_budget_exactly_at_limit():
    chatbot_module.CHATBOT_DAILY_TOKEN_LIMIT = 100000
    chatbot_module._record_usage(50000, 50000)  # exactly 100,000
    within_budget, _ = chatbot_module.check_daily_budget()
    assert within_budget is False  # < not <=


def test_budget_custom_limit():
    chatbot_module.CHATBOT_DAILY_TOKEN_LIMIT = 5000
    chatbot_module._record_usage(3000, 1000)  # 4,000 — under 5,000
    within_budget, _ = chatbot_module.check_daily_budget()
    assert within_budget is True

    chatbot_module._record_usage(1000, 500)  # now 5,500 — over 5,000
    within_budget, _ = chatbot_module.check_daily_budget()
    assert within_budget is False


# ── ask() integration ─────────────────────────────────────────────────────────

def test_ask_blocked_when_over_budget():
    """ask() returns budget message without calling API when over limit."""
    chatbot_module.CHATBOT_DAILY_TOKEN_LIMIT = 100
    chatbot_module._record_usage(50, 60)  # 110 total — over 100

    with patch("leagueintel.reporting.chatbot.client") as mock_client:
        text, fig = chatbot_module.ask("Who had the best waiver pickup in 2025?")

        # API should never have been called
        mock_client.messages.create.assert_not_called()

        # response should be the budget message
        assert "limit" in text.lower()
        assert fig is None
