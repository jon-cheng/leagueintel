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


def test_does_not_duplicate_when_a_second_leg_already_has_real_items(conn):
    """
    Regression test for a real 2021 trade (Jarvis Landry / Courtland
    Sutton): ESPN gave team 2 TWO separate transaction rows for this
    trade -- one with the real items attached (a TRADE_ACCEPT), and a
    second, otherwise-identical-looking TRADE_ACCEPT with no items of
    its own. That second row still counts as "unresolved" by itself,
    and pairs up with team 4's own unresolved leg to form a matchable
    2-team pool -- so diffing would happily re-derive Landry/Sutton and
    write a duplicate on top of the real ESPN data. The player-level
    already-recorded check must catch this and skip both players.
    """
    # team 2's leg WITH real items
    _insert_transaction(
        conn, "team2-leg-with-items", 2021, "TRADE_ACCEPT", "EXECUTED", 2, 16, None
    )
    conn.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id, source)
        VALUES ('team2-leg-with-items', 'TRADE', 3128429, 4, 2, 'ESPN')
        """
    )
    conn.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id, source)
        VALUES ('team2-leg-with-items', 'TRADE', 16790, 2, 4, 'ESPN')
        """
    )

    # team 2's SECOND leg for the same trade, no items of its own
    _insert_transaction(
        conn, "team2-leg-empty", 2021, "TRADE_ACCEPT", None, 2, 16, None
    )
    # team 4's only leg, also no items
    _insert_transaction(
        conn, "team4-leg-empty", 2021, "TRADE_UPHOLD", "EXECUTED", 4, 16, None
    )

    # rosters reflect the same real swap
    _insert_box_score(conn, 2021, 15, 4, 3128429)
    _insert_box_score(conn, 2021, 15, 2, 16790)
    _insert_box_score(conn, 2021, 16, 4, 16790)
    _insert_box_score(conn, 2021, 16, 2, 3128429)

    conn.commit()

    infer_missing_trade_items(conn, season=2021)

    moves = conn.execute(
        """
        SELECT item_type, player_id, from_team_id, to_team_id, source
        FROM transaction_moves
        ORDER BY player_id
        """
    ).fetchall()

    assert moves == [
        ("TRADE", 16790, 2, 4, "ESPN"),
        ("TRADE", 3128429, 4, 2, "ESPN"),
    ]


def test_canceled_proposal_for_same_player_week_does_not_block_real_trade(conn):
    """
    Regression test for a real 2022 trade: a CANCELED TRADE_PROPOSAL for
    Tua Tagovailoa existed in the same week as (but unrelated to) a real
    3-player trade that also included Tua. The already-recorded check
    matched on item_type='TRADE' + player_id + week alone, without
    checking status/transaction_type, so it mistook the canceled,
    never-completed proposal for "this player's trade already has real
    data" and wrongly excluded Tua from the real, executed trade.
    """
    # unrelated CANCELED proposal touching the same player/week
    _insert_transaction(
        conn, "unrelated-proposal", 2022, "TRADE_PROPOSAL", "CANCELED", 1, 16, None
    )
    conn.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id, source)
        VALUES ('unrelated-proposal', 'TRADE', 4241479, 1, 12, 'ESPN')
        """
    )

    # the real trade: team 9 sends Tua (4241479) to team 1 for Watson (3122840)
    _insert_transaction(conn, "team9-leg", 2022, "TRADE_UPHOLD", "EXECUTED", 9, 16, None)
    _insert_transaction(conn, "team1-leg", 2022, "TRADE_UPHOLD", "EXECUTED", 1, 16, None)

    _insert_box_score(conn, 2022, 15, 9, 4241479)
    _insert_box_score(conn, 2022, 15, 1, 3122840)
    _insert_box_score(conn, 2022, 16, 9, 3122840)
    _insert_box_score(conn, 2022, 16, 1, 4241479)

    conn.commit()

    infer_missing_trade_items(conn, season=2022)

    inferred = conn.execute(
        """
        SELECT item_type, player_id, from_team_id, to_team_id, source
        FROM transaction_moves
        WHERE source = 'INFERRED'
        ORDER BY player_id
        """
    ).fetchall()

    assert inferred == [
        ("TRADE", 3122840, 1, 9, "INFERRED"),
        ("TRADE", 4241479, 9, 1, "INFERRED"),
    ]


def test_resolves_trade_when_partner_has_no_transaction_row_at_all(conn):
    """
    Regression test for a real 2024 trade (Baker Mayfield / Rachaad
    White): team 1's leg was linked via related_transaction_id to team
    6 -- a completely unrelated team that never received or sent either
    player -- while team 9, the real partner, had ZERO transaction rows
    for this trade at all. Grouping must diff every team in the league
    that week (not just teams with their own leftover leg), and must
    anchor team 9's inferred move to SOME valid transaction row even
    though team 9 has none of its own.
    """
    # team 1's leg, misleadingly linked to team 6 via related_transaction_id
    _insert_transaction(conn, "team1-leg", 2024, "TRADE_ACCEPT", None, 1, 13, "shared-id")
    # team 6's leg -- same related_transaction_id, but team 6 is NOT
    # actually involved in this trade at all
    _insert_transaction(conn, "team6-leg", 2024, "TRADE_UPHOLD", "EXECUTED", 6, 13, "shared-id")
    # team 9 (the real partner) has NO transaction row whatsoever

    # rosters: team1 gives up Mayfield, gets White; team9 gives up White, gets Mayfield
    _insert_box_score(conn, 2024, 12, 1, 3052587)  # team1 has Mayfield
    _insert_box_score(conn, 2024, 12, 9, 4697815)  # team9 has White
    _insert_box_score(conn, 2024, 12, 6, 99999)  # team6 uninvolved, unrelated player

    _insert_box_score(conn, 2024, 13, 1, 4697815)  # team1 now has White
    _insert_box_score(conn, 2024, 13, 9, 3052587)  # team9 now has Mayfield
    _insert_box_score(conn, 2024, 13, 6, 99999)  # team6 unchanged

    conn.commit()

    infer_missing_trade_items(conn, season=2024)

    moves = conn.execute(
        """
        SELECT item_type, player_id, from_team_id, to_team_id, source
        FROM transaction_moves
        ORDER BY player_id
        """
    ).fetchall()

    assert moves == [
        ("TRADE", 3052587, 1, 9, "INFERRED"),
        ("TRADE", 4697815, 9, 1, "INFERRED"),
    ]


def test_canceled_waiver_attempt_does_not_block_real_trade_leg(conn):
    """
    Regression test for a real 2024 trade (Kareem Hunt / Christian Kirk):
    a CANCELED waiver DROP attempt for Christian Kirk existed for the
    same team/week as his real trade departure. _already_explained_players
    checked item_type + team + week without checking status, so it
    treated the canceled, never-executed waiver attempt as "already
    explains this departure" and wrongly excluded Kirk from the real
    trade -- only Hunt's side of the swap got inferred, not Kirk's.
    """
    _insert_transaction(conn, "team3-leg", 2024, "TRADE_ACCEPT", None, 3, 6, None)
    _insert_transaction(conn, "team13-leg", 2024, "TRADE_UPHOLD", "EXECUTED", 13, 6, None)

    # unrelated CANCELED waiver drop attempt for the same player/team/week
    _insert_transaction(conn, "canceled-waiver", 2024, "WAIVER", "CANCELED", 3, 6, None)
    conn.execute(
        """
        INSERT INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id, to_team_id, source)
        VALUES ('canceled-waiver', 'DROP', 3895856, 3, 0, 'ESPN')
        """
    )

    # real trade: team3 gives Kirk (3895856) for team13's Hunt (3059915)
    _insert_box_score(conn, 2024, 5, 3, 3895856)
    _insert_box_score(conn, 2024, 5, 13, 3059915)
    _insert_box_score(conn, 2024, 6, 3, 3059915)
    _insert_box_score(conn, 2024, 6, 13, 3895856)

    conn.commit()

    infer_missing_trade_items(conn, season=2024)

    moves = conn.execute(
        """
        SELECT item_type, player_id, from_team_id, to_team_id, source
        FROM transaction_moves
        WHERE source = 'INFERRED'
        ORDER BY player_id
        """
    ).fetchall()

    assert moves == [
        ("TRADE", 3059915, 13, 3, "INFERRED"),
        ("TRADE", 3895856, 3, 13, "INFERRED"),
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
