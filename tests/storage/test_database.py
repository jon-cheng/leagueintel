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
