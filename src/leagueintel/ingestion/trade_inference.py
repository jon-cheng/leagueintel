"""
Reconstructs trade items ESPN's API drops from its response.

ESPN's per-week transaction feed only carries player items on the
TRADE_PROPOSAL transaction. Once a trade is accepted/upheld, the proposal
is no longer returned by the API, leaving only empty-item TRADE_ACCEPT/
TRADE_UPHOLD stubs behind. This module reconstructs the missing player
items by diffing each involved team's box_score roster the week before
and the week of the trade.

Known limitation: a player traded twice in the same week (e.g. A->B, then
B->C) can't be resolved. The intermediate team's roster shows no net
change for the week -- received and gave up the same player before the
next box_score snapshot -- so neither leg's drop/add sets match and both
are skipped (logged as "could not reconstruct"). Rare in practice.
"""

import sqlite3
from collections import defaultdict
from loguru import logger

from leagueintel.storage.writer import write_transaction_moves

TRADE_RESOLUTION_TYPES = ("TRADE_ACCEPT", "TRADE_UPHOLD")


def _group_unresolved_trades(conn: sqlite3.Connection, season: int) -> list[dict]:
    """
    Group TRADE_ACCEPT/TRADE_UPHOLD legs by related_transaction_id (the
    shared parent proposal). Skip any group where a member transaction
    already has transaction_moves rows -- real ESPN data or a prior
    inference run, either way there's nothing to do.
    """
    rows = conn.execute(
        """
        SELECT id, transaction_type, team_id, scoring_period_id, related_transaction_id
        FROM transactions
        WHERE season = ?
        AND transaction_type IN ('TRADE_ACCEPT', 'TRADE_UPHOLD')
        AND related_transaction_id IS NOT NULL
        """,
        (season,),
    ).fetchall()

    groups: dict[str, dict] = {}
    for tx_id, tx_type, team_id, week, related_id in rows:
        group = groups.setdefault(
            related_id, {"legs": [], "team_ids": set(), "week": week}
        )
        group["legs"].append((tx_id, tx_type))
        group["team_ids"].add(team_id)

    unresolved = []
    for related_id, group in groups.items():
        leg_ids = [tx_id for tx_id, _ in group["legs"]]
        placeholders = ",".join("?" * len(leg_ids))
        already_has_moves = conn.execute(
            f"SELECT 1 FROM transaction_moves WHERE transaction_id IN ({placeholders}) LIMIT 1",
            leg_ids,
        ).fetchone()
        if already_has_moves:
            continue

        # anchor inferred rows to a leg that actually exists as a row --
        # the related_transaction_id (the vanished parent proposal) does not
        anchor_id = next(
            (tx_id for tx_id, tx_type in group["legs"] if tx_type == "TRADE_UPHOLD"),
            group["legs"][0][0],
        )
        unresolved.append(
            {
                "related_transaction_id": related_id,
                "anchor_transaction_id": anchor_id,
                "team_ids": group["team_ids"],
                "week": group["week"],
            }
        )
    return unresolved


def _week_roster(conn: sqlite3.Connection, season: int, week: int, team_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT DISTINCT player_id FROM box_scores WHERE season = ? AND week = ? AND team_id = ?",
        (season, week, team_id),
    ).fetchall()
    return {r[0] for r in rows}


def _already_explained_players(
    conn: sqlite3.Connection, season: int, week: int, team_id: int, item_type: str
) -> set[int]:
    """Players whose roster change that week is already accounted for by a
    non-trade transaction (waiver add/drop, draft, etc.) -- these shouldn't
    be misattributed to the trade being inferred."""
    team_column = "to_team_id" if item_type == "ADD" else "from_team_id"
    rows = conn.execute(
        f"""
        SELECT DISTINCT tm.player_id
        FROM transaction_moves tm
        JOIN transactions t ON tm.transaction_id = t.id
        WHERE t.season = ? AND t.scoring_period_id = ? AND tm.{team_column} = ?
        AND tm.item_type = ?
        """,
        (season, week, team_id, item_type),
    ).fetchall()
    return {r[0] for r in rows}


def infer_missing_trade_items(conn: sqlite3.Connection, season: int) -> int:
    """
    Find trades with no player items and reconstruct them by diffing
    each involved team's roster between the week before and the week of
    the trade. Writes inferred moves with source='INFERRED'.

    Returns the number of trades successfully inferred.
    """
    unresolved = _group_unresolved_trades(conn, season)
    inferred_count = 0

    for group in unresolved:
        week = group["week"]
        team_ids = group["team_ids"]

        if week is None or week <= 1:
            logger.warning(
                f"Skipping trade {group['related_transaction_id']}: "
                f"no prior week to diff against (week={week})"
            )
            continue

        dropped_by_team: dict[int, set[int]] = {}
        added_by_team: dict[int, set[int]] = {}

        for team_id in team_ids:
            before = _week_roster(conn, season, week - 1, team_id)
            after = _week_roster(conn, season, week, team_id)

            explained_adds = _already_explained_players(conn, season, week, team_id, "ADD")
            explained_drops = _already_explained_players(conn, season, week, team_id, "DROP")

            dropped_by_team[team_id] = (before - after) - explained_drops
            added_by_team[team_id] = (after - before) - explained_adds

        # match each dropped player to whichever group member added it
        moves = []
        all_dropped = {p for players in dropped_by_team.values() for p in players}
        all_added = {p for players in added_by_team.values() for p in players}
        matched_players = all_dropped & all_added

        for player_id in matched_players:
            from_team = next(t for t, players in dropped_by_team.items() if player_id in players)
            to_team = next(t for t, players in added_by_team.items() if player_id in players)
            moves.append(
                {
                    "transaction_id": group["anchor_transaction_id"],
                    "item_type": "TRADE",
                    "player_id": player_id,
                    "from_team_id": from_team,
                    "to_team_id": to_team,
                    "source": "INFERRED",
                }
            )

        if not moves:
            logger.warning(
                f"Could not reconstruct trade {group['related_transaction_id']} "
                f"(season={season}, week={week}, teams={team_ids}) -- "
                "no matching dropped/added players found"
            )
            continue

        write_transaction_moves(moves, conn)
        inferred_count += 1

    return inferred_count


def infer_missing_trade_items_all(seasons: list[int] = None) -> None:
    from leagueintel.config import ALL_SEASONS
    from leagueintel.storage.database import get_connection

    seasons = seasons or ALL_SEASONS
    conn = get_connection()

    for season in seasons:
        count = infer_missing_trade_items(conn, season)
        logger.info(f"Season {season}: inferred {count} trade(s)")

    conn.close()
