# src/leagueintel/analytics/waiver.py
"""
Waiver wire analytics — position-normalized percentile scoring.

Methodology:
  For each waiver pickup with >= 8 weeks on roster:
    1. Select the player's top 8 scoring weeks
    2. Sum those 8 weeks → player's total
    3. Compare that total against all rostered players at the same
       position over the SAME 8 weeks
    4. Percentile = fraction of comparison players who scored less × 100

This rewards consistent performers and controls for position scarcity
and schedule difficulty by comparing against the field over the same weeks.

Originally based on espnff waiver analysis methodology.
"""

import pandas as pd
from leagueintel.storage.database import get_connection

WAIVER_SCORE_SQL = """
WITH params AS (
    SELECT :season AS season
),
drafted_players AS (
    SELECT DISTINCT
        tm.player_id,
        t.season
    FROM transaction_moves tm
    JOIN transactions t ON tm.transaction_id = t.id
    CROSS JOIN params p
    WHERE t.transaction_type = 'DRAFT'
    AND t.status = 'EXECUTED'
    AND t.season = p.season
    AND tm.item_type = 'DRAFT'
    AND tm.player_id > 0
),
waiver_adds AS (
    SELECT
        tm.player_id,
        tm.to_team_id AS team_id,
        MIN(t.scoring_period_id) AS acquisition_week,
        t.season
    FROM transaction_moves tm
    JOIN transactions t ON tm.transaction_id = t.id
    CROSS JOIN params p
    WHERE tm.item_type = 'ADD'
    AND t.transaction_type = 'WAIVER'
    AND t.status = 'EXECUTED'
    AND t.season = p.season
    AND tm.player_id > 0
    AND tm.player_id NOT IN (
        SELECT player_id FROM drafted_players
        WHERE season = p.season
    )
    GROUP BY tm.player_id, tm.to_team_id, t.season
),
waiver_drops AS (
    SELECT
        tm.player_id,
        tm.from_team_id AS team_id,
        MIN(t.scoring_period_id) AS drop_week,
        t.season
    FROM transaction_moves tm
    JOIN transactions t ON tm.transaction_id = t.id
    CROSS JOIN params p
    WHERE tm.item_type = 'DROP'
    AND t.season = p.season
    AND tm.player_id > 0
    GROUP BY tm.player_id, tm.from_team_id, t.season
),
stints AS (
    SELECT
        a.player_id,
        a.team_id,
        a.season,
        a.acquisition_week,
        COALESCE(d.drop_week, 18) AS drop_week
    FROM waiver_adds a
    LEFT JOIN waiver_drops d
        ON a.player_id = d.player_id
        AND a.team_id = d.team_id
        AND a.season = d.season
        AND d.drop_week > a.acquisition_week
),
stint_scores AS (
    SELECT
        s.player_id,
        s.team_id,
        s.season,
        s.acquisition_week,
        s.drop_week,
        bs.week,
        bs.points,
        bs.position
    FROM stints s
    JOIN box_scores bs
        ON s.player_id = bs.player_id
        AND s.team_id = bs.team_id
        AND s.season = bs.season
        AND bs.week >= s.acquisition_week
        AND bs.week < s.drop_week
    WHERE bs.position NOT IN ('K', 'D/ST')
),
top_8_weeks AS (
    SELECT
        player_id,
        team_id,
        season,
        acquisition_week,
        drop_week,
        week,
        points,
        position,
        ROW_NUMBER() OVER (
            PARTITION BY player_id, team_id, season, acquisition_week
            ORDER BY points DESC
        ) AS week_rank
    FROM stint_scores
),
top_8 AS (
    SELECT *
    FROM top_8_weeks
    WHERE week_rank <= 8
),
player_top8_totals AS (
    SELECT
        player_id,
        team_id,
        season,
        acquisition_week,
        drop_week,
        position,
        SUM(points) AS top8_total_points,
        COUNT(*) AS num_weeks
    FROM top_8
    GROUP BY player_id, team_id, season, acquisition_week, drop_week, position
    HAVING COUNT(*) >= 8
),
comparison_totals AS (
    SELECT
        pt.player_id AS query_player_id,
        pt.team_id AS query_team_id,
        pt.season AS query_season,
        pt.acquisition_week AS query_acquisition_week,
        pt.position AS query_position,
        pt.top8_total_points AS query_total,
        pt.num_weeks,
        bs.player_id AS comparison_player_id,
        SUM(bs.points) AS comparison_total
    FROM player_top8_totals pt
    JOIN top_8 t8
        ON pt.player_id = t8.player_id
        AND pt.team_id = t8.team_id
        AND pt.season = t8.season
        AND pt.acquisition_week = t8.acquisition_week
    JOIN box_scores bs
        ON bs.week = t8.week
        AND bs.season = pt.season
        AND bs.position = pt.position
    WHERE bs.position NOT IN ('K', 'D/ST')
    GROUP BY
        pt.player_id,
        pt.team_id,
        pt.season,
        pt.acquisition_week,
        pt.position,
        pt.top8_total_points,
        pt.num_weeks,
        bs.player_id
),
quantile_scores AS (
    SELECT
        query_player_id AS player_id,
        query_team_id AS team_id,
        query_season AS season,
        query_acquisition_week AS acquisition_week,
        query_position AS position,
        num_weeks,
        query_total AS total_points,
        ROUND(
            100.0 * SUM(CASE WHEN comparison_total < query_total THEN 1 ELSE 0 END)
            / COUNT(*),
            1
        ) AS waiver_score
    FROM comparison_totals
    GROUP BY
        query_player_id,
        query_team_id,
        query_season,
        query_acquisition_week,
        query_position,
        num_weeks,
        query_total
)
SELECT
    p.full_name AS player_name,
    tm.team_name,
    tm.owner_name,
    qs.position,
    qs.acquisition_week,
    qs.num_weeks,
    qs.total_points,
    qs.waiver_score
FROM quantile_scores qs
JOIN players p ON qs.player_id = p.player_id
JOIN teams tm
    ON qs.team_id = tm.team_id
    AND qs.season = tm.season
ORDER BY qs.waiver_score DESC
"""


def get_waiver_scores(season: int) -> pd.DataFrame:
    """
    Compute waiver wire value scores for all eligible pickups in a season.

    Eligibility:
      - Player was not drafted (waiver add only)
      - Player was rostered for at least 8 weeks
      - Position is QB, RB, WR, or TE (K and D/ST excluded)

    Returns DataFrame with columns:
      player_name, team_name, owner_name, position,
      acquisition_week, num_weeks, total_points, waiver_score

    waiver_score: 0-100 percentile — fraction of all rostered players
    at the same position who scored less over the same 8 weeks.
    """
    conn = get_connection()
    df = pd.read_sql(WAIVER_SCORE_SQL, conn, params={"season": season})
    conn.close()
    return df
