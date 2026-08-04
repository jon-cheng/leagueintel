import sqlite3
import pytest
from leagueintel.storage.database import create_tables
from leagueintel.ingestion.trade_inference import infer_missing_trade_items


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    create_tables(connection)
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
    related_transaction_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO transactions
        (id, season, transaction_type, status, team_id, scoring_period_id, related_transaction_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (id, season, transaction_type, status, team_id, scoring_period_id, related_transaction_id),
    )


def _insert_box_score(conn, season: int, week: int, team_id: int, player_id: int) -> None:
    conn.execute(
        """
        INSERT INTO box_scores (season, week, team_id, player_id)
        VALUES (?, ?, ?, ?)
        """,
        (season, week, team_id, player_id),
    )


def test_infers_simple_two_team_one_for_one_trade(conn):
    """
    Team 6 traded Keenan Allen (15818) to team 10 for Drake Maye (4431452)
    in week 7, 2025 -- this is the real trade that surfaced the bug: ESPN's
    TRADE_UPHOLD/TRADE_ACCEPT legs carry no player items, only the vanished
    parent TRADE_PROPOSAL did. Roster-diffing week 6 -> week 7 should
    reconstruct both legs of the trade.
    """
    _insert_transaction(
        conn, "uphold-1", 2025, "TRADE_UPHOLD", "EXECUTED", 6, 7, "parent-1"
    )
    _insert_transaction(
        conn, "accept-1", 2025, "TRADE_ACCEPT", None, 10, 7, "parent-1"
    )

    # week 6 rosters (before the trade)
    _insert_box_score(conn, 2025, 6, 6, 15818)  # team 6 has Allen
    _insert_box_score(conn, 2025, 6, 10, 4431452)  # team 10 has Maye

    # week 7 rosters (after the trade)
    _insert_box_score(conn, 2025, 7, 6, 4431452)  # team 6 now has Maye
    _insert_box_score(conn, 2025, 7, 10, 15818)  # team 10 now has Allen

    conn.commit()

    infer_missing_trade_items(conn, season=2025)

    moves = conn.execute(
        """
        SELECT item_type, player_id, from_team_id, to_team_id, source
        FROM transaction_moves
        ORDER BY player_id
        """
    ).fetchall()

    assert moves == [
        ("TRADE", 15818, 6, 10, "INFERRED"),
        ("TRADE", 4431452, 10, 6, "INFERRED"),
    ]


def test_does_not_duplicate_on_rerun(conn):
    """Running inference twice must not double-insert the same inferred moves."""
    _insert_transaction(
        conn, "uphold-1", 2025, "TRADE_UPHOLD", "EXECUTED", 6, 7, "parent-1"
    )
    _insert_transaction(
        conn, "accept-1", 2025, "TRADE_ACCEPT", None, 10, 7, "parent-1"
    )
    _insert_box_score(conn, 2025, 6, 6, 15818)
    _insert_box_score(conn, 2025, 6, 10, 4431452)
    _insert_box_score(conn, 2025, 7, 6, 4431452)
    _insert_box_score(conn, 2025, 7, 10, 15818)
    conn.commit()

    infer_missing_trade_items(conn, season=2025)
    infer_missing_trade_items(conn, season=2025)

    count = conn.execute("SELECT COUNT(*) FROM transaction_moves").fetchone()[0]
    assert count == 2


def test_excludes_confounding_waiver_moves_same_week(conn):
    """
    The same week as the Allen/Maye trade, player 77777 happens to move
    from team 6 to team 10 via an ordinary waiver claim -- dropped by team 6,
    picked up by team 10, same direction as the trade. A naive roster diff
    (drop-by-one-team matched to add-by-another) would wrongly fold this
    into the trade. Because it's already explained by a WAIVER transaction,
    it must be excluded -- only Allen/Maye should be inferred.
    """
    _insert_transaction(
        conn, "uphold-1", 2025, "TRADE_UPHOLD", "EXECUTED", 6, 7, "parent-1"
    )
    _insert_transaction(
        conn, "accept-1", 2025, "TRADE_ACCEPT", None, 10, 7, "parent-1"
    )

    # unrelated waiver move the same week, same two teams, same direction
    _insert_transaction(
        conn, "waiver-drop-1", 2025, "WAIVER", "EXECUTED", 6, 7, None
    )
    _insert_transaction(
        conn, "waiver-add-1", 2025, "WAIVER", "EXECUTED", 10, 7, None
    )
    conn.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id, source)
        VALUES ('waiver-drop-1', 'DROP', 77777, 6, 0, 'ESPN')
        """
    )
    conn.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id, source)
        VALUES ('waiver-add-1', 'ADD', 77777, 0, 10, 'ESPN')
        """
    )

    # week 6 rosters (before the trade) -- team 6 also has the soon-to-be-waived player
    _insert_box_score(conn, 2025, 6, 6, 15818)  # team 6 has Allen
    _insert_box_score(conn, 2025, 6, 6, 77777)  # team 6 also has the waiver player
    _insert_box_score(conn, 2025, 6, 10, 4431452)  # team 10 has Maye

    # week 7 rosters (after the trade) -- team 10 now has the waiver pickup too
    _insert_box_score(conn, 2025, 7, 6, 4431452)  # team 6 now has Maye
    _insert_box_score(conn, 2025, 7, 10, 15818)  # team 10 now has Allen
    _insert_box_score(conn, 2025, 7, 10, 77777)  # team 10 now has the waiver pickup

    conn.commit()

    infer_missing_trade_items(conn, season=2025)

    inferred_moves = conn.execute(
        """
        SELECT item_type, player_id, from_team_id, to_team_id, source
        FROM transaction_moves
        WHERE source = 'INFERRED'
        ORDER BY player_id
        """
    ).fetchall()

    assert inferred_moves == [
        ("TRADE", 15818, 6, 10, "INFERRED"),
        ("TRADE", 4431452, 10, 6, "INFERRED"),
    ]


def test_handles_one_team_trading_with_two_different_counterparties_same_week(conn):
    """
    Team 6 makes two separate trades the same week: Allen to team 10 for
    Maye, AND (independently) player 11111 to team 20 for player 22222.
    Each trade is its own related_transaction_id group. The player-unique
    box_score snapshot per week means a correct implementation resolves
    both trades without cross-contaminating players between them.
    """
    _insert_transaction(
        conn, "uphold-1", 2025, "TRADE_UPHOLD", "EXECUTED", 6, 7, "parent-1"
    )
    _insert_transaction(
        conn, "accept-1", 2025, "TRADE_ACCEPT", None, 10, 7, "parent-1"
    )
    _insert_transaction(
        conn, "uphold-2", 2025, "TRADE_UPHOLD", "EXECUTED", 6, 7, "parent-2"
    )
    _insert_transaction(
        conn, "accept-2", 2025, "TRADE_ACCEPT", None, 20, 7, "parent-2"
    )

    # week 6 rosters (before both trades)
    _insert_box_score(conn, 2025, 6, 6, 15818)  # team 6 has Allen
    _insert_box_score(conn, 2025, 6, 6, 11111)  # team 6 also has player going to team 20
    _insert_box_score(conn, 2025, 6, 10, 4431452)  # team 10 has Maye
    _insert_box_score(conn, 2025, 6, 20, 22222)  # team 20 has the player coming to team 6

    # week 7 rosters (after both trades)
    _insert_box_score(conn, 2025, 7, 6, 4431452)  # team 6 now has Maye
    _insert_box_score(conn, 2025, 7, 6, 22222)  # team 6 now has the player from team 20
    _insert_box_score(conn, 2025, 7, 10, 15818)  # team 10 now has Allen
    _insert_box_score(conn, 2025, 7, 20, 11111)  # team 20 now has the player from team 6

    conn.commit()

    infer_missing_trade_items(conn, season=2025)

    moves = conn.execute(
        """
        SELECT item_type, player_id, from_team_id, to_team_id, source
        FROM transaction_moves
        ORDER BY player_id
        """
    ).fetchall()

    assert moves == [
        ("TRADE", 11111, 6, 20, "INFERRED"),
        ("TRADE", 15818, 6, 10, "INFERRED"),
        ("TRADE", 22222, 20, 6, "INFERRED"),
        ("TRADE", 4431452, 10, 6, "INFERRED"),
    ]


def test_skips_trade_that_already_has_real_items(conn):
    """A trade ESPN already gave us items for should be left alone, not re-inferred."""
    _insert_transaction(
        conn, "uphold-1", 2025, "TRADE_UPHOLD", "EXECUTED", 6, 7, "parent-1"
    )
    conn.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id, source)
        VALUES ('uphold-1', 'TRADE', 99999, 6, 10, 'ESPN')
        """
    )
    conn.commit()

    infer_missing_trade_items(conn, season=2025)

    moves = conn.execute("SELECT source FROM transaction_moves").fetchall()
    assert moves == [("ESPN",)]
