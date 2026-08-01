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
    _create_waiver_stints_view(conn)
    _create_roster_stints_view(conn)
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


def _create_waiver_stints_view(conn: sqlite3.Connection) -> None:
    """
    Waiver-added player stints on fantasy teams — one row per continuous
    roster stint for a player who was picked up off waivers (drafted
    players are excluded; they're covered by draft_picks/draft_box_scores).

    acquisition_week: first scoring period the player was added via waiver
    drop_week: scoring period the player was dropped by the SAME team that
               added them, or 18 (past the season) if never dropped
    duration_weeks: drop_week - acquisition_week. 0 means the team added
                     and dropped the player within the same scoring week
                     (a "regrettable drop" — kept as a real, visible stint
                     rather than merged or discarded; filter
                     duration_weeks > 0 downstream to exclude these)

    Each add is paired with that SAME team's next drop by rank (1st add with
    that team pairs with their 1st drop, 2nd with 2nd, etc.) — not with the
    next drop event for the player globally, which could belong to a
    different team and produce overlapping stints across teams.

    Use for: waiver value analyses — join to box_scores on
    (player_id, team_id, season) and filter week within [acquisition_week, drop_week).
    """
    conn.execute("""
        CREATE VIEW IF NOT EXISTS waiver_stints AS
        WITH drafted_players AS (
            SELECT DISTINCT
                tm.player_id,
                t.season
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE t.transaction_type = 'DRAFT'
            AND t.status = 'EXECUTED'
            AND tm.item_type = 'DRAFT'
            AND tm.player_id > 0
        ),
        waiver_adds AS (
            SELECT
                tm.player_id,
                tm.to_team_id AS team_id,
                t.season,
                t.scoring_period_id AS acquisition_week,
                ROW_NUMBER() OVER (
                    PARTITION BY tm.player_id, tm.to_team_id, t.season
                    ORDER BY t.scoring_period_id
                ) AS stint_seq
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE tm.item_type = 'ADD'
            AND t.transaction_type = 'WAIVER'
            AND t.status = 'EXECUTED'
            AND tm.player_id > 0
            AND NOT EXISTS (
                SELECT 1 FROM drafted_players dp
                WHERE dp.player_id = tm.player_id
                AND dp.season = t.season
            )
            GROUP BY tm.player_id, tm.to_team_id, t.season, t.scoring_period_id
        ),
        waiver_drops AS (
            SELECT
                tm.player_id,
                tm.from_team_id AS team_id,
                t.season,
                t.scoring_period_id AS drop_week,
                ROW_NUMBER() OVER (
                    PARTITION BY tm.player_id, tm.from_team_id, t.season
                    ORDER BY t.scoring_period_id
                ) AS stint_seq
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE tm.item_type = 'DROP'
            AND tm.player_id > 0
            GROUP BY tm.player_id, tm.from_team_id, t.season, t.scoring_period_id
        )
        SELECT
            a.player_id,
            a.team_id,
            a.season,
            a.acquisition_week,
            COALESCE(d.drop_week, 18) AS drop_week,
            COALESCE(d.drop_week, 18) - a.acquisition_week AS duration_weeks
        FROM waiver_adds a
        LEFT JOIN waiver_drops d
            ON a.player_id = d.player_id
            AND a.team_id = d.team_id
            AND a.season = d.season
            AND a.stint_seq = d.stint_seq
    """)


def _create_roster_stints_view(conn: sqlite3.Connection) -> None:
    """
    Generalized roster stints — one row per continuous roster stint for a
    player on a team, across EVERY acquisition path (draft, waiver,
    free agent, trade). Unlike waiver_stints, drafted players are included
    here — this view is for tenure/regret analyses, not waiver eligibility.

    acquisition_type: DRAFT, WAIVER, FREEAGENT, or TRADE — how the player
                       arrived on this team
    acquisition_week: week the player arrived. Drafted players always show
                       acquisition_week = 1 (the draft itself), since a
                       roster spot is held from the start of the season.
    drop_week: week the SAME team's next departure (drop or traded away)
               happened, or 18 if never left that team
    duration_weeks: drop_week - acquisition_week. 0 means the team
                     acquired and gave up the player in the same scoring
                     week — e.g. drafted and immediately cut before Week 1
                     games, or a same-week waiver add/drop. A real,
                     deliberate stint, not a data artifact — the same
                     "regrettable move" signal as waiver_stints'
                     duration_weeks = 0, generalized to any acquisition type.

    A trade is both a drop for the sending team and an add for the
    receiving team, sourced from the same transaction row.

    Use for: roster tenure / "regrettable drop" analyses across all
    acquisition types. For waiver-pickup value/eligibility specifically
    (which must exclude drafted players), use waiver_stints instead.
    """
    conn.execute("""
        CREATE VIEW IF NOT EXISTS roster_stints AS
        WITH roster_adds AS (
            SELECT
                tm.player_id,
                tm.to_team_id AS team_id,
                t.season,
                t.scoring_period_id AS acquisition_week,
                'DRAFT' AS acquisition_type
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE tm.item_type = 'DRAFT'
            AND t.transaction_type = 'DRAFT'
            AND t.status = 'EXECUTED'
            AND tm.player_id > 0

            UNION ALL

            SELECT
                tm.player_id,
                tm.to_team_id AS team_id,
                t.season,
                t.scoring_period_id AS acquisition_week,
                'WAIVER' AS acquisition_type
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE tm.item_type = 'ADD'
            AND t.transaction_type = 'WAIVER'
            AND t.status = 'EXECUTED'
            AND tm.player_id > 0

            UNION ALL

            SELECT
                tm.player_id,
                tm.to_team_id AS team_id,
                t.season,
                t.scoring_period_id AS acquisition_week,
                'FREEAGENT' AS acquisition_type
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE tm.item_type = 'ADD'
            AND t.transaction_type = 'FREEAGENT'
            AND t.status = 'EXECUTED'
            AND tm.player_id > 0

            UNION ALL

            SELECT
                tm.player_id,
                tm.to_team_id AS team_id,
                t.season,
                t.scoring_period_id AS acquisition_week,
                'TRADE' AS acquisition_type
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE tm.item_type = 'TRADE'
            AND t.transaction_type = 'TRADE_ACCEPT'
            AND t.status = 'EXECUTED'
            AND tm.player_id > 0
        ),
        roster_adds_ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY player_id, team_id, season
                    ORDER BY acquisition_week
                ) AS stint_seq
            FROM roster_adds
        ),
        roster_drops AS (
            SELECT
                tm.player_id,
                tm.from_team_id AS team_id,
                t.season,
                t.scoring_period_id AS drop_week
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE tm.item_type = 'DROP'
            AND t.status = 'EXECUTED'
            AND tm.player_id > 0

            UNION ALL

            SELECT
                tm.player_id,
                tm.from_team_id AS team_id,
                t.season,
                t.scoring_period_id AS drop_week
            FROM transaction_moves tm
            JOIN transactions t ON tm.transaction_id = t.id
            WHERE tm.item_type = 'TRADE'
            AND t.transaction_type = 'TRADE_ACCEPT'
            AND t.status = 'EXECUTED'
            AND tm.player_id > 0
        ),
        roster_drops_ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY player_id, team_id, season
                    ORDER BY drop_week
                ) AS stint_seq
            FROM roster_drops
        )
        SELECT
            a.player_id,
            a.team_id,
            a.season,
            a.acquisition_type,
            a.acquisition_week,
            COALESCE(d.drop_week, 18) AS drop_week,
            COALESCE(d.drop_week, 18) - a.acquisition_week AS duration_weeks
        FROM roster_adds_ranked a
        LEFT JOIN roster_drops_ranked d
            ON a.player_id = d.player_id
            AND a.team_id = d.team_id
            AND a.season = d.season
            AND a.stint_seq = d.stint_seq
    """)
