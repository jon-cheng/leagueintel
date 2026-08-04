import sqlite3
import pytest
from leagueintel.storage.database import create_tables
from leagueintel.storage.views import create_views


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    create_tables(connection)
    create_views(connection)
    yield connection
    connection.close()


def _insert_transaction(
    conn,
    id: str,
    season: int,
    transaction_type: str,
    status: str | None,
    team_id: int,
    scoring_period_id: int,
) -> None:
    conn.execute(
        """
        INSERT INTO transactions
        (id, season, transaction_type, status, team_id, scoring_period_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (id, season, transaction_type, status, team_id, scoring_period_id),
    )


def _insert_trade_move(
    conn, transaction_id: str, player_id: int, from_team_id: int, to_team_id: int
) -> None:
    conn.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id)
        VALUES (?, 'TRADE', ?, ?, ?)
        """,
        (transaction_id, player_id, from_team_id, to_team_id),
    )


def _acquisition_rows_for_player(conn, player_id: int):
    return conn.execute(
        """
        SELECT team_id, acquisition_type, acquisition_week
        FROM roster_stints
        WHERE player_id = ?
        ORDER BY team_id
        """,
        (player_id,),
    ).fetchall()


def test_trade_upheld_appears_as_trade_for_both_teams(conn):
    """
    Most real trades resolve via TRADE_UPHOLD, not TRADE_ACCEPT -- the
    original view only matched TRADE_ACCEPT, silently dropping the
    majority of real trades (including the inferred Allen/Maye trade)
    from roster_stints.
    """
    _insert_transaction(conn, "uphold-1", 2025, "TRADE_UPHOLD", "EXECUTED", 6, 7)
    _insert_trade_move(conn, "uphold-1", 15818, from_team_id=6, to_team_id=10)
    conn.commit()

    rows = _acquisition_rows_for_player(conn, 15818)
    assert rows == [(10, "TRADE", 7)]


def test_trade_accept_with_null_status_still_counts(conn):
    """
    ESPN never marks a TRADE_ACCEPT leg's own status EXECUTED -- it stays
    NULL even for real, completed trades. A strict status='EXECUTED'
    filter would drop these; NULL must be treated as executed.
    """
    _insert_transaction(conn, "accept-1", 2025, "TRADE_ACCEPT", None, 10, 7)
    _insert_trade_move(conn, "accept-1", 4431452, from_team_id=10, to_team_id=6)
    conn.commit()

    rows = _acquisition_rows_for_player(conn, 4431452)
    assert rows == [(6, "TRADE", 7)]


def test_canceled_trade_is_excluded(conn):
    """A CANCELED trade proposal/accept must not show up as a real roster move."""
    _insert_transaction(conn, "accept-1", 2025, "TRADE_ACCEPT", "CANCELED", 10, 7)
    _insert_trade_move(conn, "accept-1", 99999, from_team_id=10, to_team_id=6)
    conn.commit()

    assert _acquisition_rows_for_player(conn, 99999) == []
