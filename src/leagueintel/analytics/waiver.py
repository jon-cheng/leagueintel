# src/leagueintel/analytics/waiver.py
"""
Waiver wire analytics — position-normalized percentile scoring for
waiver-only pickups.

Thin wrapper around stint_scoring.compute_stint_scores: waiver-specific
behavior is just the stint source (waiver_stints, so drafted players are
excluded) and top_n_weeks == min_weeks == 8 — only established pickups
with a full 8-week sample are ranked. See stint_scoring.py for the shared
percentile methodology, and roster_value.py for the generalized version
covering every acquisition type with a relaxed eligibility floor.

Stint boundaries (who was on which team, and when) come from the
waiver_stints SQL view — matching add/drop transactions into date ranges
is naturally a join and stays in SQL. Everything downstream (picking each
stint's best weeks, building the comparison population, scoring) is pandas.
"""

import pandas as pd
from leagueintel.storage.database import get_connection, get_max_ingested_week
from leagueintel.analytics.availability import check_season_ready
from leagueintel.analytics.stint_scoring import compute_stint_scores

TOP_N_WEEKS = 8

WAIVER_STINTS_SQL = "SELECT * FROM waiver_stints WHERE season = :season"

BOX_SCORES_SQL = """
    SELECT player_id, team_id, season, week, points, position
    FROM box_scores
    WHERE season = :season
    AND position NOT IN ('K', 'D/ST')
"""

TEAMS_SQL = "SELECT team_id, season, team_name, owner_name FROM teams WHERE season = :season"

PLAYERS_SQL = "SELECT player_id, full_name AS player_name FROM players"

RESULT_COLUMNS = [
    "player_name",
    "team_name",
    "owner_name",
    "position",
    "acquisition_week",
    "num_weeks",
    "total_points",
    "waiver_score",
]


def get_waiver_scores(season: int) -> pd.DataFrame:
    """
    Compute waiver wire value scores for all eligible pickups in a season.

    Eligibility:
      - Player was not drafted (waiver add only)
      - Player was rostered for at least TOP_N_WEEKS weeks
      - Position is QB, RB, WR, or TE (K and D/ST excluded)

    Returns DataFrame with columns:
      player_name, team_name, owner_name, position,
      acquisition_week, num_weeks, total_points, waiver_score

    waiver_score: 0-100 percentile — fraction of all rostered players
    at the same position who scored less over the same weeks.

    Raises SeasonNotReadyError if the current season hasn't reached
    LIVE_SEASON_ANALYSIS_MIN_WEEK yet.
    """
    conn = get_connection()
    check_season_ready(season, get_max_ingested_week(conn, season))

    stints = pd.read_sql(WAIVER_STINTS_SQL, conn, params={"season": season})
    box_scores = pd.read_sql(BOX_SCORES_SQL, conn, params={"season": season})
    players = pd.read_sql(PLAYERS_SQL, conn)
    teams = pd.read_sql(TEAMS_SQL, conn, params={"season": season})
    conn.close()

    return compute_waiver_scores(stints, box_scores, players, teams)


def compute_waiver_scores(
    stints: pd.DataFrame,
    box_scores: pd.DataFrame,
    players: pd.DataFrame,
    teams: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute waiver wire percentile scores from stint boundaries and weekly
    box scores. Pure function — no DB access — so it can be tested with
    hand-built DataFrames.

    Thin wrapper around stint_scoring.compute_stint_scores with
    top_n_weeks == min_weeks == TOP_N_WEEKS — see that module for the
    shared percentile methodology.

    Args:
        stints: one row per waiver stint — player_id, team_id, season,
            acquisition_week, drop_week (from the waiver_stints view)
        box_scores: player_id, team_id, season, week, points, position —
            K and D/ST already excluded upstream
        players: player_id, player_name
        teams: team_id, season, team_name, owner_name
    """
    scores = compute_stint_scores(
        stints, box_scores, players, teams,
        top_n_weeks=TOP_N_WEEKS, min_weeks=TOP_N_WEEKS,
    )
    if scores.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)
    return scores[RESULT_COLUMNS]
