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

Grouping is by manager's acquisition of a player, not by individual add
event: a manager who waiver-added, dropped, and re-added the same player
gets ONE scored entry pooling their best weeks across every stint of that
SAME acquisition_type. That's the question this answers — "how good was
this manager at getting value out of this player" — not "how good was
this one claim." Stints of a DIFFERENT acquisition_type for the same
manager/player (e.g. drafted, then later re-added off waivers) stay
separate entries, since that's a different kind of move being judged.
acquisition_week in the result is the FIRST time that manager acquired
the player via that acquisition_type, not necessarily the start of a
single continuous window.
"""

import pandas as pd

STINT_KEY = ["player_id", "team_id", "season", "acquisition_type"]

RESULT_COLUMNS = [
    "player_id",
    "team_id",
    "season",
    "player_name",
    "team_name",
    "owner_name",
    "position",
    "acquisition_type",
    "acquisition_week",
    "num_weeks",
    "total_points",
    "weeks",
    "median_total_points",
    "waiver_score",
]


POPULATION_COLUMNS = [
    "player_id",
    "team_id",
    "season",
    "acquisition_type",
    "query_total_points",
    "weeks",
    "median_total_points",
    "comparison_player_id",
    "comparison_player_name",
    "comparison_team_id",
    "comparison_team_name",
    "comparison_owner_name",
    "comparison_total",
    "comparison_ppg",
    "is_query_player",
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

    Thin wrapper around compute_stint_scores_with_population that drops the
    comparison population — use that instead if you need the raw field
    (e.g. for a "show me the comparison" drilldown), not just the score.

    Args: see compute_stint_scores_with_population.
    """
    result, _population = compute_stint_scores_with_population(
        stints, box_scores, players, teams, top_n_weeks, min_weeks
    )
    return result


def compute_stint_scores_with_population(
    stints: pd.DataFrame,
    box_scores: pd.DataFrame,
    players: pd.DataFrame,
    teams: pd.DataFrame,
    top_n_weeks: int,
    min_weeks: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute position-normalized percentile scores from stint boundaries and
    weekly box scores, AND the raw comparison population behind each score.
    Pure function — no DB access — so it can be tested with hand-built
    DataFrames.

    Returns (result, population):
      result: same shape as compute_stint_scores' return — one row per
          scored manager/player acquisition.
      population: one row per (scored acquisition, comparison player) —
          the individual field players waiver_score/median_total_points
          were computed FROM. Columns: player_id, team_id, season,
          acquisition_type (identify which result row this population
          belongs to — join on these four), query_total_points, weeks,
          median_total_points (that result row's own total_points/weeks/
          median_total_points, for convenience — median_total_points is
          the comparison field's median TOTAL points over these weeks,
          the number actually consistent with waiver_score's percentile
          basis; see the comment above median_total_points' computation
          for why a PPG-based median has no such guaranteed relationship),
          and per comparison player: comparison_player_id,
          comparison_player_name, comparison_team_id, comparison_team_name,
          comparison_owner_name, comparison_total, comparison_ppg (that
          player's own points per game over the weeks THEY were rostered
          within the query's qualifying weeks — not comparison_total /
          num_weeks, since a comparison player isn't guaranteed to have
          been rostered every one of those weeks), is_query_player (True
          for the scored player's own row within their own comparison
          pool — see methodology note above
          on why it's included).

    Args:
        stints: one row per roster stint — player_id, team_id, season,
            acquisition_type, acquisition_week, drop_week
        box_scores: player_id, team_id, season, week, points, position —
            K and D/ST already excluded upstream
        players: player_id, player_name
        teams: team_id, season, team_name, owner_name
        top_n_weeks: cap on how many of a manager's best scoring weeks
            (pooled across all their same-acquisition_type stints for
            this player) to sum
        min_weeks: minimum qualifying weeks required, pooled across those
            stints, for a manager's acquisition of this player to be
            scored at all
    """
    # Stints with zero duration (acquisition_week == drop_week, e.g. a
    # same-week add/drop or a drafted-and-immediately-cut player) had no
    # real week on the roster and must contribute nothing to scoring.
    stints = stints[stints["drop_week"] > stints["acquisition_week"]]

    # stint_scores: each stint's box scores while actually on the roster.
    # A manager's discontinuous stints of the same acquisition_type for a
    # player (e.g. waiver-added, dropped, re-added) each contribute their
    # own weeks here — merged into one pool below via STINT_KEY.
    stint_scores = stints.merge(box_scores, on=["player_id", "team_id", "season"])
    stint_scores = stint_scores[
        (stint_scores["week"] >= stint_scores["acquisition_week"])
        & (stint_scores["week"] < stint_scores["drop_week"])
    ]

    # top_n_weeks / topn: each manager's best top_n_weeks scoring weeks,
    # pooled across all their same-acquisition_type stints for this
    # player. groupby().rank() is pandas' equivalent of a SQL window
    # function — SQL's ROW_NUMBER() OVER (PARTITION BY ... ORDER BY
    # points DESC) becomes "rank within each group," since pandas has no
    # windowed, non-aggregating op outside of groupby.
    stint_scores["week_rank"] = stint_scores.groupby(STINT_KEY)["points"].rank(
        method="first", ascending=False
    )
    topn = stint_scores[stint_scores["week_rank"] <= top_n_weeks]

    # totals: only manager/player acquisitions with at least min_weeks
    # pooled qualifying weeks count. acquisition_week is the FIRST time
    # this manager acquired the player this way — drop_week isn't
    # meaningful once stints are pooled (each sub-stint can have its own),
    # so it's dropped rather than grouped on. weeks is the chronological
    # identity of which weeks made the top_n_weeks cut, for transparency —
    # so callers can show "his best 8 weeks were weeks 1, 4, 6..." rather
    # than just the aggregated total.
    totals = (
        topn.groupby(STINT_KEY + ["position"])
        .agg(
            acquisition_week=("acquisition_week", "min"),
            total_points=("points", "sum"),
            num_weeks=("week", "count"),
            weeks=("week", lambda s: sorted(s.tolist())),
        )
        .reset_index()
    )
    totals = totals[totals["num_weeks"] >= min_weeks]

    if totals.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS), pd.DataFrame(columns=POPULATION_COLUMNS)

    # restrict to the specific stint-weeks that qualified
    qualifying_weeks = topn.merge(totals[STINT_KEY], on=STINT_KEY)

    # comparison_totals: for each qualifying stint, every player rostered
    # at the same position during those exact weeks, summed over those weeks
    comparisons = qualifying_weeks[STINT_KEY + ["position", "week"]].merge(
        box_scores, on=["season", "position", "week"], suffixes=("_query", "")
    )
    comparison_group = ["player_id_query", "team_id_query", "season", "acquisition_type", "position"]
    # Grouped by player_id only (not team_id) — a comparison player traded
    # mid-stint keeps ONE combined total across both teams. This must
    # match exactly, or a traded comparison player's points get split into
    # two smaller partial totals, each more likely to register as "scored
    # less" than the query player's full total — silently inflating
    # waiver_score. team_id (for population display only, below) is
    # derived separately so it can never affect this computation.
    comparison_totals = (
        comparisons.groupby(comparison_group + ["player_id"])["points"]
        .sum()
        .reset_index(name="comparison_total")
    )

    # median_total_points: the whole comparison field's MEDIAN total
    # points over those exact same weeks — transparency companion to
    # waiver_score, and on the SAME basis waiver_score itself is computed
    # from (total points, not rate): if the query player's total_points
    # is above this median, more than half the field scored less, i.e.
    # waiver_score >= ~50. Deliberately left as a raw total, not divided
    # into a PPG — every comparison total here is already measured over
    # the exact same window as the query's own total_points, so there's
    # no unit mismatch to fix. Converting to PPG would require assuming
    # every comparison player played the same number of games, which
    # isn't true and would distort the number (see git history/PR
    # discussion for a worked example of that distortion).
    median_total_points = (
        comparison_totals.groupby(comparison_group)["comparison_total"]
        .median()
        .round(1)
        .reset_index(name="median_total_points")
    )

    # quantile_scores: percentile = fraction of comparison players who
    # scored less than the query player's total over those same weeks.
    # .mean() on a boolean column is "fraction True" — the pandas shortcut
    # for SQL's SUM(CASE WHEN ... THEN 1 ELSE 0 END) / COUNT(*).
    scored = comparison_totals.merge(
        totals.rename(columns={"player_id": "player_id_query", "team_id": "team_id_query"}),
        on=["player_id_query", "team_id_query", "season", "acquisition_type", "position"],
    ).merge(median_total_points, on=comparison_group)
    scored["scored_less"] = scored["comparison_total"] < scored["total_points"]

    # population: the raw comparison field behind each score, for
    # transparency drilldowns (e.g. a beeswarm of every comparison total).
    # is_query_player flags the scored player's own row within their own
    # comparison pool — see the methodology note above on why their own
    # rows are included (mirrors the original SQL; never biases the score
    # since a value can't be "less than" itself).
    #
    # team_id here is a DISPLAY-ONLY lookup (last team_id seen for that
    # comparison player during the qualifying weeks) — kept fully separate
    # from comparison_totals above so it can never influence scoring.
    comparison_team = (
        comparisons.groupby(comparison_group + ["player_id"])["team_id"]
        .last()
        .reset_index()
    )
    # comparison_ppg: each comparison player's own points-per-game over
    # the weeks THEY were actually rostered within the query's qualifying
    # weeks — not comparison_total / num_weeks, since a comparison player
    # isn't guaranteed to have been rostered every one of those weeks.
    comparison_games = (
        comparisons.groupby(comparison_group + ["player_id"])["week"]
        .count()
        .reset_index(name="comparison_games")
    )
    comparison_ppg = comparison_totals.merge(
        comparison_games, on=comparison_group + ["player_id"]
    )
    comparison_ppg["comparison_ppg"] = (
        comparison_ppg["comparison_total"] / comparison_ppg["comparison_games"]
    ).round(1)
    comparison_ppg = comparison_ppg[comparison_group + ["player_id", "comparison_ppg"]]

    population = scored.merge(comparison_team, on=comparison_group + ["player_id"]).merge(
        comparison_ppg, on=comparison_group + ["player_id"]
    ).rename(
        columns={
            "player_id_query": "player_id",
            "team_id_query": "team_id",
            "player_id": "comparison_player_id",
            "team_id": "comparison_team_id",
            "total_points": "query_total_points",
        }
    ).merge(
        players.rename(columns={"player_id": "comparison_player_id", "player_name": "comparison_player_name"}),
        on="comparison_player_id",
    ).merge(
        teams.rename(
            columns={
                "team_id": "comparison_team_id",
                "team_name": "comparison_team_name",
                "owner_name": "comparison_owner_name",
            }
        ),
        on=["comparison_team_id", "season"],
    )
    population["is_query_player"] = (
        (population["comparison_player_id"] == population["player_id"])
        & (population["comparison_team_id"] == population["team_id"])
    )
    population = population[POPULATION_COLUMNS].reset_index(drop=True)

    waiver_scores = (
        scored.groupby(
            ["player_id_query", "team_id_query", "season", "acquisition_type",
             "acquisition_week", "position", "num_weeks", "total_points"]
        )
        .agg(
            waiver_score=("scored_less", "mean"),
            weeks=("weeks", "first"),
            median_total_points=("median_total_points", "first"),
        )
        .reset_index()
        .rename(columns={"player_id_query": "player_id", "team_id_query": "team_id"})
    )
    waiver_scores["waiver_score"] = waiver_scores["waiver_score"].mul(100).round(1)

    result = waiver_scores.merge(players, on="player_id").merge(teams, on=["team_id", "season"])
    result = (
        result[RESULT_COLUMNS]
        .sort_values("waiver_score", ascending=False)
        .reset_index(drop=True)
    )
    return result, population
