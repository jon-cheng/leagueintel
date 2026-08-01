# src/leagueintel/analytics/roster_value.py
"""
Roster acquisition value — position-normalized percentile scoring across
EVERY acquisition path (draft, waiver, free agent, trade), not just
waiver pickups.

Same methodology as waiver.py's waiver-value scoring (see
stint_scoring.compute_stint_scores), but:
  - sourced from roster_stints instead of waiver_stints, so drafted and
    traded players are included
  - MIN_WEEKS relaxed to 1 instead of requiring a full TOP_N_WEEKS sample,
    since this is meant to answer "was this acquisition a good move" for
    any single stint (e.g. a specific draft pick or trade), not just rank
    a large field of established waiver pickups.

Small-sample results (num_weeks well below TOP_N_WEEKS) are noisier —
num_weeks is included in the output so callers can judge confidence.
"""

import pandas as pd
from leagueintel.storage.database import get_connection, get_max_ingested_week
from leagueintel.analytics.availability import check_season_ready
from leagueintel.analytics.stint_scoring import compute_stint_scores, STINT_KEY

TOP_N_WEEKS = 8
MIN_WEEKS = 1

ROSTER_STINTS_SQL = "SELECT * FROM roster_stints WHERE season = :season"

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
    "acquisition_type",
    "acquisition_week",
    "num_weeks",
    "total_points",
    "value_score",
]


def get_roster_value_scores(season: int) -> pd.DataFrame:
    """
    Compute roster acquisition value scores for every stint in a season,
    across all acquisition types (draft, waiver, free agent, trade).

    Returns DataFrame with columns:
      player_name, team_name, owner_name, position, acquisition_type,
      acquisition_week, num_weeks, total_points, value_score

    value_score: 0-100 percentile — fraction of all rostered players
    at the same position who scored less over the same weeks.

    Raises SeasonNotReadyError if the current season hasn't reached
    LIVE_SEASON_ANALYSIS_MIN_WEEK yet.
    """
    conn = get_connection()
    check_season_ready(season, get_max_ingested_week(conn, season))

    stints = pd.read_sql(ROSTER_STINTS_SQL, conn, params={"season": season})
    box_scores = pd.read_sql(BOX_SCORES_SQL, conn, params={"season": season})
    players = pd.read_sql(PLAYERS_SQL, conn)
    teams = pd.read_sql(TEAMS_SQL, conn, params={"season": season})
    conn.close()

    return compute_roster_value_scores(stints, box_scores, players, teams)


def compute_roster_value_scores(
    stints: pd.DataFrame,
    box_scores: pd.DataFrame,
    players: pd.DataFrame,
    teams: pd.DataFrame,
) -> pd.DataFrame:
    """
    Pure function — no DB access. See stint_scoring.compute_stint_scores
    for the core percentile methodology.

    Args:
        stints: one row per roster stint — player_id, team_id, season,
            acquisition_type, acquisition_week, drop_week (from the
            roster_stints view)
        box_scores: player_id, team_id, season, week, points, position —
            K and D/ST already excluded upstream
        players: player_id, player_name
        teams: team_id, season, team_name, owner_name
    """
    scores = compute_stint_scores(
        stints, box_scores, players, teams,
        top_n_weeks=TOP_N_WEEKS, min_weeks=MIN_WEEKS,
    ).rename(columns={"waiver_score": "value_score"})

    if scores.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    acquisition_types = stints[STINT_KEY + ["acquisition_type"]].drop_duplicates()
    result = scores.merge(acquisition_types, on=STINT_KEY)
    return result[RESULT_COLUMNS]
