# src/leagueintel/analytics/stint_scoring.py
"""
Position-normalized percentile scoring — shared engine for comparing any
player's roster stint against the field at the same position, over the
same weeks.

Methodology:
  For each stint with >= min_weeks qualifying weeks:
    1. Select the player's top top_n_weeks scoring weeks
    2. Sum those weeks -> player's total
    3. Compare that total against all rostered players at the same
       position over the SAME weeks
    4. Percentile = fraction of comparison players who scored less x 100

This rewards consistent performers and controls for position scarcity
and schedule difficulty by comparing against the field over the same weeks.

Originally based on espnff waiver analysis methodology.

Two callers use this with different parameters and stint sources:
  - waiver.py: waiver_stints only, top_n_weeks == min_weeks == 8
    (a large field of established waiver pickups)
  - roster_value.py: roster_stints (every acquisition type), min_weeks
    relaxed to 1 (answering "was this acquisition a good move" for any
    single stint, not just ranking a large field)
"""

import pandas as pd

STINT_KEY = ["player_id", "team_id", "season", "acquisition_week"]

RESULT_COLUMNS = [
    "player_id",
    "team_id",
    "season",
    "player_name",
    "team_name",
    "owner_name",
    "position",
    "acquisition_week",
    "num_weeks",
    "total_points",
    "waiver_score",
]


def compute_stint_scores(
    stints: pd.DataFrame,
    box_scores: pd.DataFrame,
    players: pd.DataFrame,
    teams: pd.DataFrame,
    top_n_weeks: int,
    min_weeks: int,
) -> pd.DataFrame:
    """
    Compute position-normalized percentile scores from stint boundaries and
    weekly box scores. Pure function — no DB access — so it can be tested
    with hand-built DataFrames.

    Args:
        stints: one row per roster stint — player_id, team_id, season,
            acquisition_week, drop_week
        box_scores: player_id, team_id, season, week, points, position —
            K and D/ST already excluded upstream
        players: player_id, player_name
        teams: team_id, season, team_name, owner_name
        top_n_weeks: cap on how many of a stint's best scoring weeks to sum
        min_weeks: minimum qualifying weeks required for a stint to be
            scored at all
    """
    # Stints with zero duration (acquisition_week == drop_week, e.g. a
    # same-week add/drop or a drafted-and-immediately-cut player) had no
    # real week on the roster and must contribute nothing to scoring.
    stints = stints[stints["drop_week"] > stints["acquisition_week"]]

    # stint_scores: each stint's box scores while actually on the roster
    stint_scores = stints.merge(box_scores, on=["player_id", "team_id", "season"])
    stint_scores = stint_scores[
        (stint_scores["week"] >= stint_scores["acquisition_week"])
        & (stint_scores["week"] < stint_scores["drop_week"])
    ]

    # top_n_weeks / topn: each stint's best top_n_weeks scoring weeks.
    # groupby().rank() is pandas' equivalent of a SQL window function —
    # SQL's ROW_NUMBER() OVER (PARTITION BY ... ORDER BY points DESC)
    # becomes "rank within each group," since pandas has no windowed,
    # non-aggregating op outside of groupby.
    stint_scores["week_rank"] = stint_scores.groupby(STINT_KEY)["points"].rank(
        method="first", ascending=False
    )
    topn = stint_scores[stint_scores["week_rank"] <= top_n_weeks]

    # totals: only stints with at least min_weeks qualify
    totals = (
        topn.groupby(STINT_KEY + ["drop_week", "position"])
        .agg(total_points=("points", "sum"), num_weeks=("week", "count"))
        .reset_index()
    )
    totals = totals[totals["num_weeks"] >= min_weeks]

    if totals.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    # restrict to the specific stint-weeks that qualified
    qualifying_weeks = topn.merge(totals[STINT_KEY], on=STINT_KEY)

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
