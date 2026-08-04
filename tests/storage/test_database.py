# tests/storage/test_database.py
import sqlite3
import pytest
from leagueintel.storage.database import create_tables, get_max_ingested_week


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    create_tables(connection)
    yield connection
    connection.close()


def _insert_matchup(conn, season: int, week: int) -> None:
    conn.execute(
        """
        INSERT INTO matchups (season, week, home_team_id, away_team_id, home_score, away_score)
        VALUES (?, ?, 1, 2, 100.0, 90.0)
        """,
        (season, week),
    )
    conn.commit()


def test_get_max_ingested_week_no_data_returns_zero(conn):
    """A season with nothing ingested yet (e.g. before Week 1) reports week 0."""
    assert get_max_ingested_week(conn, season=2026) == 0


def test_get_max_ingested_week_returns_latest_week(conn):
    for week in (1, 2, 3):
        _insert_matchup(conn, season=2026, week=week)
    assert get_max_ingested_week(conn, season=2026) == 3


def test_get_max_ingested_week_ignores_other_seasons(conn):
    """Rows from other seasons shouldn't leak into the current season's max week."""
    _insert_matchup(conn, season=2025, week=17)
    _insert_matchup(conn, season=2026, week=4)
    assert get_max_ingested_week(conn, season=2026) == 4


def test_create_tables_migrates_transaction_moves_missing_source_column():
    """
    Older DBs were created before `source` existed on transaction_moves.
    create_tables() must add the column via ALTER TABLE without touching
    existing rows, and those rows should default to 'ESPN' (real ingested
    data, not inferred).
    """
    connection = sqlite3.connect(":memory:")
    connection.execute("""
        CREATE TABLE transaction_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT NOT NULL,
            item_type TEXT,
            player_id INTEGER,
            from_team_id INTEGER,
            to_team_id INTEGER,
            overall_pick_number INTEGER
        )
    """)
    connection.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id)
        VALUES ('tx-1', 'TRADE', 15818, 6, 10)
        """
    )
    connection.commit()

    create_tables(connection)

    columns = {row[1] for row in connection.execute("PRAGMA table_info(transaction_moves)")}
    assert "source" in columns

    row = connection.execute(
        "SELECT source FROM transaction_moves WHERE transaction_id = 'tx-1'"
    ).fetchone()
    assert row[0] == "ESPN"
    connection.close()
