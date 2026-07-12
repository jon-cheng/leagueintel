# src/leagueintel/analytics/waiver.py
"""
Waiver wire analytics — position-normalized percentile scoring.

Methodology:
  For each waiver pickup with >= TOP_N_WEEKS weeks on roster:
    1. Select the player's top TOP_N_WEEKS scoring weeks
    2. Sum those weeks -> player's total
    3. Compare that total against all rostered players at the same
       position over the SAME weeks
    4. Percentile = fraction of comparison players who scored less x 100

This rewards consistent performers and controls for position scarcity
and schedule difficulty by comparing against the field over the same weeks.

Originally based on espnff waiver analysis methodology.

Stint boundaries (who was on which team, and when) come from the
waiver_stints SQL view — matching add/drop transactions into date ranges
is naturally a join and stays in SQL. Everything downstream (picking each
stint's best weeks, building the comparison population, scoring) is pandas.
"""

import pandas as pd
from leagueintel.storage.database import get_connection, get_max_ingested_week
from leagueintel.analytics.availability import check_season_ready

TOP_N_WEEKS = 8

STINT_KEY = ["player_id", "team_id", "season", "acquisition_week"]

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

    Args:
        stints: one row per waiver stint — player_id, team_id, season,
            acquisition_week, drop_week (from the waiver_stints view)
        box_scores: player_id, team_id, season, week, points, position —
            K and D/ST already excluded upstream
        players: player_id, player_name
        teams: team_id, season, team_name, owner_name
    """
    # stint_scores: each stint's box scores while actually on the roster
    stint_scores = stints.merge(box_scores, on=["player_id", "team_id", "season"])
    stint_scores = stint_scores[
        (stint_scores["week"] >= stint_scores["acquisition_week"])
        & (stint_scores["week"] < stint_scores["drop_week"])
    ]

    # top_8_weeks / top_8: each stint's best TOP_N_WEEKS scoring weeks.
    # groupby().rank() is pandas' equivalent of a SQL window function —
    # SQL's ROW_NUMBER() OVER (PARTITION BY ... ORDER BY points DESC)
    # becomes "rank within each group," since pandas has no windowed,
    # non-aggregating op outside of groupby.
    stint_scores["week_rank"] = stint_scores.groupby(STINT_KEY)["points"].rank(
        method="first", ascending=False
    )
    top8 = stint_scores[stint_scores["week_rank"] <= TOP_N_WEEKS]

    # player_top8_totals: only stints with a full TOP_N_WEEKS qualify
    totals = (
        top8.groupby(STINT_KEY + ["drop_week", "position"])
        .agg(total_points=("points", "sum"), num_weeks=("week", "count"))
        .reset_index()
    )
    totals = totals[totals["num_weeks"] >= TOP_N_WEEKS]

    if totals.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    # restrict to the specific stint-weeks that qualified
    qualifying_weeks = top8.merge(totals[STINT_KEY], on=STINT_KEY)

    # comparison_totals: for each qualifying stint, every player rostered
    # at the same position during those exact weeks, summed over those weeks
    comparisons = qualifying_weeks[STINT_KEY + ["position", "week"]].merge(
        box_scores, on=["season", "position", "week"], suffixes=("_query", "")
    )
    comparison_totals = (
        comparisons.groupby(
            ["player_id_query", "team_id_query", "season", "acquisition_week", "position", "player_id"]
        )["points"]
        .sum()
        .reset_index(name="comparison_total")
    )

    # quantile_scores: percentile = fraction of comparison players who
    # scored less than the query player's total over those same weeks.
    # .mean() on a boolean column is "fraction True" — the pandas shortcut
    # for SQL's SUM(CASE WHEN ... THEN 1 ELSE 0 END) / COUNT(*).
    scored = comparison_totals.merge(
        totals.rename(columns={"player_id": "player_id_query", "team_id": "team_id_query"}),
        on=["player_id_query", "team_id_query", "season", "acquisition_week", "position"],
    )
    scored["scored_less"] = scored["comparison_total"] < scored["total_points"]

    waiver_scores = (
        scored.groupby(
            ["player_id_query", "team_id_query", "season", "acquisition_week",
             "position", "num_weeks", "total_points"]
        )["scored_less"]
        .mean()
        .mul(100)
        .round(1)
        .reset_index(name="waiver_score")
        .rename(columns={"player_id_query": "player_id", "team_id_query": "team_id"})
    )

    result = waiver_scores.merge(players, on="player_id").merge(teams, on=["team_id", "season"])
    return (
        result[RESULT_COLUMNS]
        .sort_values("waiver_score", ascending=False)
        .reset_index(drop=True)
    )
