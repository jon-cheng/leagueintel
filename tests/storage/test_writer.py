# tests/storage/test_writer.py
import sqlite3
import pytest
from leagueintel.storage.database import create_tables
from leagueintel.storage.writer import (
    write_box_scores,
    write_transactions,
    write_transaction_moves,
)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    create_tables(connection)
    yield connection
    connection.close()


def _box_score(points: float = 10.0, team_id: int = 1, player_id: int = 100, week: int = 5) -> dict:
    return {
        "season": 2026,
        "week": week,
        "team_id": team_id,
        "player_id": player_id,
        "player_name": "Test Player",
        "position": "RB",
        "lineup_slot": "RB",
        "pro_team": "SF",
        "points": points,
        "projected_points": 10.0,
        "on_bye_week": 0,
        "game_played": 100,
    }


def test_write_box_scores_refreshes_points_on_reingest(conn):
    """
    Re-running ingestion mid-week (e.g. daily cron before Monday Night
    Football settles) must overwrite stale points, not freeze the first
    value written — this is the in-season refresh scenario.
    """
    write_box_scores([_box_score(points=5.0)], conn)
    write_box_scores([_box_score(points=12.5)], conn)

    row = conn.execute(
        "SELECT points FROM box_scores WHERE season = 2026 AND week = 5 AND player_id = 100"
    ).fetchone()
    assert row == (12.5,)


def test_write_box_scores_does_not_duplicate_rows_on_reingest(conn):
    write_box_scores([_box_score(points=5.0)], conn)
    write_box_scores([_box_score(points=12.5)], conn)

    count = conn.execute(
        "SELECT COUNT(*) FROM box_scores WHERE season = 2026 AND week = 5 AND player_id = 100"
    ).fetchone()[0]
    assert count == 1


def _week_rows(conn, week: int = 5) -> list[tuple]:
    return conn.execute(
        "SELECT team_id, player_id FROM box_scores WHERE season = 2026 AND week = ? ORDER BY 1, 2",
        (week,),
    ).fetchall()


def test_write_box_scores_removes_player_no_longer_on_team(conn):
    """
    Protects against ghost rows: a player dropped since the week was last
    written must disappear from that team's week. Deleting only the
    players present in the new fetch left dropped players behind forever,
    so they looked rostered (with 0 points) in weeks they weren't.
    """
    write_box_scores([_box_score(player_id=100), _box_score(player_id=101)], conn)
    write_box_scores([_box_score(player_id=100)], conn)

    assert _week_rows(conn) == [(1, 100)]


def test_write_box_scores_leaves_teams_missing_from_fetch_untouched(conn):
    """
    Protects against a partial fetch wiping data: replacement is scoped to
    the teams actually present in the new rows, so a team ESPN didn't
    return this time keeps its existing week.
    """
    write_box_scores([_box_score(team_id=1, player_id=100), _box_score(team_id=2, player_id=200)], conn)
    write_box_scores([_box_score(team_id=1, player_id=100)], conn)

    assert _week_rows(conn) == [(1, 100), (2, 200)]


def test_write_box_scores_player_moved_teams_appears_once(conn):
    """
    Protects against a player showing on two teams in the same week when a
    partial fetch includes only his NEW team: the per-player delete still
    removes his old team's row.
    """
    write_box_scores([_box_score(team_id=1, player_id=100)], conn)
    write_box_scores([_box_score(team_id=3, player_id=100)], conn)

    assert _week_rows(conn) == [(3, 100)]


def test_write_box_scores_leaves_other_weeks_untouched(conn):
    """Protects against replacement leaking outside the week being written."""
    write_box_scores([_box_score(week=4, player_id=101)], conn)
    write_box_scores([_box_score(week=5, player_id=100)], conn)

    assert _week_rows(conn, week=4) == [(1, 101)]


def _transaction(status: str) -> dict:
    return {
        "id": "abc123",
        "season": 2026,
        "transaction_type": "WAIVER",
        "status": status,
        "bid_amount": 25,
        "team_id": 1,
        "scoring_period_id": 5,
        "execution_type": "EXECUTE",
        "proposed_date": 1000,
        "process_date": None,
        "related_transaction_id": None,
    }


def test_write_transactions_refreshes_status_on_reparse(conn):
    """
    Re-parsing a transaction whose status has since transitioned (e.g.
    PENDING -> EXECUTED after ESPN processes waivers) must overwrite the
    stale status, not freeze the first value written.
    """
    write_transactions([_transaction(status="PENDING")], conn)
    write_transactions([_transaction(status="EXECUTED")], conn)

    row = conn.execute(
        "SELECT status FROM transactions WHERE id = 'abc123'"
    ).fetchone()
    assert row == ("EXECUTED",)


def test_write_transactions_does_not_duplicate_rows_on_reparse(conn):
    write_transactions([_transaction(status="PENDING")], conn)
    write_transactions([_transaction(status="EXECUTED")], conn)

    count = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE id = 'abc123'"
    ).fetchone()[0]
    assert count == 1


def _move(item_type: str) -> dict:
    return {
        "transaction_id": "abc123",
        "item_type": item_type,
        "player_id": 200,
        "from_team_id": 0,
        "to_team_id": 1,
        "overall_pick_number": None,
    }


def test_write_transaction_moves_does_not_duplicate_on_reparse(conn):
    """
    transaction_moves has no UNIQUE constraint, so re-parsing the same raw
    JSON on a daily in-season refresh would duplicate every move row on
    each run unless prior moves for that transaction are cleared first.
    """
    write_transaction_moves([_move("ADD")], conn)
    write_transaction_moves([_move("ADD")], conn)

    count = conn.execute(
        "SELECT COUNT(*) FROM transaction_moves WHERE transaction_id = 'abc123'"
    ).fetchone()[0]
    assert count == 1
