"""
leagueintel analytics views — SQL view definitions.

Views provide clean, pre-joined surfaces for analytics and LLM queries.
Think of them as the data API layer over the normalized tables.
"""

import sqlite3


def create_views(conn: sqlite3.Connection) -> None:
    """Create all leagueintel views."""
    _create_draft_picks_view(conn)
    _create_draft_box_scores_view(conn)
    conn.commit()


def _create_draft_picks_view(conn: sqlite3.Connection) -> None:
    """
    Draft picks summary — one row per draft pick.
    No box score data. Use for draft order and bid analysis.

    Common queries:
        - Filter by season for single season draft board
        - ORDER BY bid_amount DESC for highest paid players
        - GROUP BY owner_name for spend by manager
        - Filter position for positional analysis
    """
    conn.execute("""
        CREATE VIEW IF NOT EXISTS draft_picks AS
        SELECT
            t.season,                          -- NFL season year
            t.bid_amount,                      -- auction draft price
            tm.team_name,                      -- fantasy team name
            tm.owner_name,                     -- manager name
            p.full_name AS player_name,        -- NFL player name
            mv.overall_pick_number,            -- overall draft pick number
            bs.position                        -- QB, RB, WR, TE
        FROM transactions t
        JOIN transaction_moves mv ON t.id = mv.transaction_id
        JOIN players p ON mv.player_id = p.player_id
        JOIN teams tm ON t.team_id = tm.team_id AND t.season = tm.season
        LEFT JOIN (
            SELECT DISTINCT player_id, team_id, season, position
            FROM box_scores
        ) bs
            ON mv.player_id = bs.player_id
            AND t.team_id = bs.team_id
            AND t.season = bs.season
        WHERE t.transaction_type = 'DRAFT'
        AND t.status = 'EXECUTED'
        AND mv.item_type = 'DRAFT'
    """)


def _create_draft_box_scores_view(conn: sqlite3.Connection) -> None:
    """
    Draft picks joined with weekly box score data.

    One row per drafted player per week.
    Excludes K and D/ST positions.

    Common queries:
        - Filter lineup_slot != 'BE' for started weeks only
        - GROUP BY player_name, bid_amount for season totals
        - Filter by season for single-season analysis
    """
    conn.execute("""
        CREATE VIEW IF NOT EXISTS draft_box_scores AS
        -- draft picks with box score performance
        -- one row per drafted player per week
        -- excludes K and D/ST positions
        -- filter lineup_slot != 'BE' for started weeks only
        -- group by player_name, bid_amount for season totals
        SELECT
            p.full_name AS player_name,       -- NFL player full name e.g. Patrick Mahomes
            t.bid_amount,                      -- FAAB dollars paid at auction draft
            t.season,                          -- NFL season year e.g. 2024
            tm.owner_name,                     -- fantasy manager first + last name
            tm.team_name,                      -- fantasy team display name
            bs.position,                       -- QB, RB, WR, TE (K and D/ST excluded)
            bs.points,                         -- actual fantasy points scored this week
            bs.lineup_slot,                    -- QB/RB/WR/TE = started, BE = bench, IR = injured
            bs.week                            -- NFL week number 1-17
        FROM transactions t
        JOIN transaction_moves mv ON t.id = mv.transaction_id
        JOIN players p ON mv.player_id = p.player_id
        JOIN teams tm ON t.team_id = tm.team_id AND t.season = tm.season
        JOIN box_scores bs
            ON mv.player_id = bs.player_id
            AND t.team_id = bs.team_id
            AND t.season = bs.season
        WHERE t.transaction_type = 'DRAFT'    -- auction draft picks only
        AND t.status = 'EXECUTED'             -- successful picks only
        AND mv.item_type = 'DRAFT'            -- keep DRAFT item type only
        AND bs.position NOT IN ('K', 'D/ST') -- exclude kickers and defenses
    """)
