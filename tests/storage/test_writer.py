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


def _box_score(points: float) -> dict:
    return {
        "season": 2026,
        "week": 5,
        "team_id": 1,
        "player_id": 100,
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
