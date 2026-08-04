"""
Reconstructs trade items ESPN's API drops from its response.

ESPN's per-week transaction feed only carries player items on the
TRADE_PROPOSAL transaction. Once a trade is accepted/upheld, the proposal
is no longer returned by the API, leaving only empty-item TRADE_ACCEPT/
TRADE_UPHOLD stubs behind. This module reconstructs the missing player
items by diffing each involved team's box_score roster the week before
and the week of the trade.

Grouping deliberately does NOT use transactions.related_transaction_id
to decide WHICH teams to diff together. It looks like a per-trade link,
but in this league's real data it's unreliable two different ways: (a)
it's been observed shared across MULTIPLE distinct trades (and vetoes)
resolved in the same batch -- one real value was attached to 7 different
transactions across 6 different teams in a single week; and (b) it can
point a team's leg at the WRONG partner entirely -- a real 2024 trade
had team 1's leg linked to team 6 via related_transaction_id, but team
1's actual trade partner that week was team 9, which had ZERO
transaction rows for the trade at all.

Instead, for any week with at least one unresolved leg, EVERY team
active that season is diffed together (derived from box_scores, not
just the teams with a leg of their own). Matching by player_id is safe
regardless of how many teams are in the pool, since box_scores
guarantees a player is dropped by at most one team and added by at most
one team in a given week -- unrelated teams' players simply don't
intersect and correctly fail to match. A move's transaction_id anchor
(needed only to satisfy the FK, not a semantic claim) prefers the
receiving team's own unresolved leg when it has one, falling back to
any other unresolved leg that week when it doesn't (as with team 9
above).

A team's own leg having no items doesn't guarantee no ESPN data exists
for that trade -- ESPN sometimes attaches the real items to a
DIFFERENT transaction row for the same team/trade (also seen in real
data). infer_missing_trade_items() cross-checks per matched player,
not just per team, before writing, to avoid duplicating those.

Known limitation: a player traded twice in the same week (e.g. A->B, then
B->C) can't be resolved. The intermediate team's roster shows no net
change for the week -- received and gave up the same player before the
next box_score snapshot -- so neither leg's drop/add sets match and both
are skipped (logged as "could not reconstruct"). Rare in practice.
"""

import sqlite3
from loguru import logger

from leagueintel.storage.writer import write_transaction_moves


def _teams_with_box_scores(conn: sqlite3.Connection, season: int) -> set[int]:
    rows = conn.execute(
        "SELECT DISTINCT team_id FROM box_scores WHERE season = ?", (season,)
    ).fetchall()
    return {r[0] for r in rows}


def _group_unresolved_trades(conn: sqlite3.Connection, season: int) -> list[dict]:
    """
    Find weeks with at least one unresolved TRADE_ACCEPT/TRADE_UPHOLD leg
    (no transaction_moves rows yet). Each such week's group includes
    EVERY team active that season -- see module docstring for why
    related_transaction_id isn't used to narrow this down.
    """
    leg_rows = conn.execute(
        """
        SELECT t.id, t.team_id, t.scoring_period_id
        FROM transactions t
        WHERE t.season = ?
        AND t.transaction_type IN ('TRADE_ACCEPT', 'TRADE_UPHOLD')
        AND NOT EXISTS (
            SELECT 1 FROM transaction_moves tm WHERE tm.transaction_id = t.id
        )
        """,
        (season,),
    ).fetchall()

    if not leg_rows:
        return []

    legs_by_week: dict[int, list[tuple[str, int]]] = {}
    for tx_id, team_id, week in leg_rows:
        legs_by_week.setdefault(week, []).append((tx_id, team_id))

    all_team_ids = _teams_with_box_scores(conn, season)

    groups = []
    for week, legs in legs_by_week.items():
        anchor_by_team: dict[int, str] = {}
        for tx_id, team_id in legs:
            # first unresolved leg seen for this team/week is anchor
            # enough -- it's just an FK target, not a semantic claim
            # about which leg "really" caused which move
            anchor_by_team.setdefault(team_id, tx_id)
        groups.append(
            {
                "week": week,
                "team_ids": all_team_ids,
                "anchor_by_team": anchor_by_team,
                # for a team with no leg of its own (real example: team 9
                # above) -- any unresolved leg that week is a valid FK target
                "fallback_anchor": legs[0][0],
            }
        )
    return groups


def _players_already_recorded(
    conn: sqlite3.Connection, season: int, week: int, player_ids: set[int]
) -> set[int]:
    """
    Which of these players already have a real, EXECUTED trade item
    recorded this week, under ANY transaction. Checked per-player, not
    per-team: a team can legitimately have multiple different trades the
    same week, and ESPN can also attach a team's real trade items to a
    transaction row other than the one used as this team's anchor --
    this catches both without over-excluding a team's other, genuinely
    unresolved trade that week.

    Must filter to TRADE_ACCEPT/TRADE_UPHOLD with an executed status --
    a CANCELED TRADE_PROPOSAL for the same player in the same week (a
    different, never-completed trade attempt) also has item_type='TRADE'
    rows and would otherwise be mistaken for "already recorded", wrongly
    excluding a real trade for that player.
    """
    if not player_ids:
        return set()
    placeholders = ",".join("?" * len(player_ids))
    rows = conn.execute(
        f"""
        SELECT DISTINCT tm.player_id
        FROM transaction_moves tm
        JOIN transactions t ON tm.transaction_id = t.id
        WHERE tm.item_type = 'TRADE'
        AND t.transaction_type IN ('TRADE_ACCEPT', 'TRADE_UPHOLD')
        AND COALESCE(t.status, 'EXECUTED') = 'EXECUTED'
        AND t.season = ? AND t.scoring_period_id = ?
        AND tm.player_id IN ({placeholders})
        """,
        (season, week, *player_ids),
    ).fetchall()
    return {r[0] for r in rows}


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
    be misattributed to the trade being inferred.

    Must filter to status='EXECUTED' -- a CANCELED/FAILED/PENDING waiver
    attempt for the same player/team/week also has an item_type row and
    would otherwise be mistaken for "already explains this roster
    change", wrongly excluding a player whose real move was the trade.
    """
    team_column = "to_team_id" if item_type == "ADD" else "from_team_id"
    rows = conn.execute(
        f"""
        SELECT DISTINCT tm.player_id
        FROM transaction_moves tm
        JOIN transactions t ON tm.transaction_id = t.id
        WHERE t.season = ? AND t.scoring_period_id = ? AND tm.{team_column} = ?
        AND tm.item_type = ?
        AND t.status = 'EXECUTED'
        """,
        (season, week, team_id, item_type),
    ).fetchall()
    return {r[0] for r in rows}


def infer_missing_trade_items(conn: sqlite3.Connection, season: int) -> int:
    """
    Find trades with no player items and reconstruct them by diffing
    each involved team's roster between the week before and the week of
    the trade. Writes inferred moves with source='INFERRED'.

    Returns the number of weeks with at least one trade successfully
    reconstructed.
    """
    unresolved = _group_unresolved_trades(conn, season)
    resolved_weeks = 0

    for group in unresolved:
        week = group["week"]
        team_ids = group["team_ids"]
        anchor_by_team = group["anchor_by_team"]
        fallback_anchor = group["fallback_anchor"]

        if week is None or week <= 1:
            logger.warning(
                f"Skipping season={season} week={week}: no prior week to diff against"
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

        # match each dropped player to whichever team in this week's pool
        # added them -- safe across multiple unrelated trades in the same
        # week, since a player can only be dropped/added by one team each
        all_dropped = {p for players in dropped_by_team.values() for p in players}
        all_added = {p for players in added_by_team.values() for p in players}
        matched_players = all_dropped & all_added

        already_recorded = _players_already_recorded(conn, season, week, matched_players)
        if already_recorded:
            logger.info(
                f"Skipping already-recorded player(s) {already_recorded} "
                f"(season={season}, week={week}) -- a different transaction "
                "already has real items for them; inferring would duplicate"
            )
            matched_players -= already_recorded

        moves = []
        for player_id in matched_players:
            from_team = next(t for t, players in dropped_by_team.items() if player_id in players)
            to_team = next(t for t, players in added_by_team.items() if player_id in players)
            moves.append(
                {
                    "transaction_id": anchor_by_team.get(to_team, fallback_anchor),
                    "item_type": "TRADE",
                    "player_id": player_id,
                    "from_team_id": from_team,
                    "to_team_id": to_team,
                    "source": "INFERRED",
                }
            )

        if not moves:
            logger.warning(
                f"Could not reconstruct any trades for season={season} week={week} "
                f"teams={team_ids} -- no matching dropped/added players found"
            )
            continue

        write_transaction_moves(moves, conn)
        resolved_weeks += 1

    return resolved_weeks


def infer_missing_trade_items_all(seasons: list[int] = None) -> None:
    from leagueintel.config import ALL_SEASONS
    from leagueintel.storage.database import get_connection

    seasons = seasons or ALL_SEASONS
    conn = get_connection()

    for season in seasons:
        count = infer_missing_trade_items(conn, season)
        logger.info(f"Season {season}: reconstructed trades in {count} week(s)")

    conn.close()
