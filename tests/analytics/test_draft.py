# tests/analytics/test_draft.py
import sqlite3
import pandas as pd
import pytest
from leagueintel.analytics.draft import compute_draft_roi, get_draft_roi, get_draft_type
from leagueintel.storage.database import create_tables


def test_compute_draft_roi_excludes_ir():
    """
    Regression test: a player on IR every week should not count
    as 'started' even though IR is not the bench slot.

    This bug was caught when Christian McCaffrey who was injured all 2024,
    showed up incorrectly with a high number of starts and low points-per-game because IR
    weeks were counted as starts.
    """
    df = pd.DataFrame(
        [
            {
                "player_name": "Injured Player",
                "bid_amount": 50,
                "owner_name": "Test",
                "position": "RB",
                "lineup_slot": "IR",
                "points": 0.0,
                "week": w,
            }
            for w in range(1, 18)
        ]
    )
    result = compute_draft_roi(df)
    assert "Injured Player" not in result["player_name"].values


def test_compute_draft_roi_min_weeks_zero_includes_low_start_players():
    """
    The Draft Selections table shows every drafted player, unlike the ROI
    plot which cuts off below MIN_WEEKS starts — min_weeks=0 must let a
    player with a single start through instead of being filtered out.
    """
    df = pd.DataFrame(
        [
            {
                "player_name": "Bench Warmer",
                "bid_amount": 5,
                "owner_name": "Test",
                "position": "WR",
                "lineup_slot": "WR",
                "points": 8.0,
                "week": 1,
            }
        ]
    )
    result = compute_draft_roi(df, min_weeks=0)
    assert "Bench Warmer" in result["player_name"].values


# ── get_draft_type / get_draft_roi dispatch tests ───────────────────────────────


@pytest.fixture
def db_conn(monkeypatch):
    """In-memory DB wired up so get_draft_type/get_draft_roi's get_connection()
    calls return it instead of touching the real DEFAULT_DB_PATH."""
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    monkeypatch.setattr("leagueintel.analytics.draft.get_connection", lambda: conn)
    yield conn
    conn.close()


def test_get_draft_type_reads_season_settings(db_conn):
    db_conn.execute(
        "INSERT INTO season_settings (season, median_scoring, draft_type) "
        "VALUES (2025, 0, 'AUCTION')"
    )
    db_conn.commit()

    assert get_draft_type(2025) == "AUCTION"


def test_get_draft_type_returns_none_for_unknown_season(db_conn):
    assert get_draft_type(1999) is None


def test_get_draft_roi_raises_for_non_auction_season(db_conn):
    """
    Snake-draft ROI isn't implemented yet (see GENERALIZATION_PLAN.md
    step 5) — a non-AUCTION season must fail loudly rather than silently
    running the auction bid-amount math against pick numbers.
    """
    db_conn.execute(
        "INSERT INTO season_settings (season, median_scoring, draft_type) "
        "VALUES (2025, 0, 'SNAKE')"
    )
    db_conn.commit()

    with pytest.raises(NotImplementedError):
        get_draft_roi(2025)
