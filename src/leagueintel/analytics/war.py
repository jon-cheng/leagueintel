"""
WAR (wins above replacement) analytics — converts a started player's
weekly points into a win-probability swing versus a real replacement-level
bench alternative, then sums that swing across the weeks they were started.

Unlike draft ROI (points per game started), WAR doesn't need bid_amount to
compute, so it works for any season regardless of draft_type — draft price
is joined on afterward, only for the auction price-vs-WAR visualization.
"""

import numpy as np
import pandas as pd
from leagueintel.storage.database import get_connection, get_max_ingested_week
from leagueintel.analytics.availability import check_season_ready

NON_STARTING_SLOTS = ["BE", "IR"]

TEAM_GAMES_SQL = """
    SELECT season, week, home_team_id AS team_id, away_team_id AS opp_team_id,
           home_score AS team_score, away_score AS opp_score
    FROM matchups
    WHERE season = :season AND away_team_id IS NOT NULL
    UNION ALL
    SELECT season, week, away_team_id AS team_id, home_team_id AS opp_team_id,
           away_score AS team_score, home_score AS opp_score
    FROM matchups
    WHERE season = :season AND away_team_id IS NOT NULL
"""

BOX_SCORES_SQL = """
    SELECT season, week, team_id, player_id, player_name, position,
           lineup_slot, points
    FROM box_scores
    WHERE season = :season AND position IN ('QB', 'RB', 'WR', 'TE')
"""

DRAFT_PRICE_SQL = """
    SELECT mv.player_id, t.bid_amount
    FROM transactions t
    JOIN transaction_moves mv ON t.id = mv.transaction_id
    WHERE t.transaction_type = 'DRAFT' AND t.status = 'EXECUTED'
      AND mv.item_type = 'DRAFT' AND t.season = :season
"""

DRAFT_ORDER_SQL = """
    SELECT mv.player_id, mv.overall_pick_number
    FROM transactions t
    JOIN transaction_moves mv ON t.id = mv.transaction_id
    WHERE t.transaction_type = 'DRAFT' AND t.status = 'EXECUTED'
      AND mv.item_type = 'DRAFT' AND t.season = :season
"""


def fit_win_probability_model(
    team_games: pd.DataFrame, learning_rate: float = 0.01, iterations: int = 2000
) -> tuple[float, float]:
    """
    Fit P(win) = sigmoid(coef * margin + intercept) by gradient descent on
    this season's real team-game margins and outcomes.

    A closed-form solver isn't available without scipy/sklearn, and a
    single-feature logistic fit converges quickly with plain gradient
    descent — no need to add a dependency for one coefficient and an
    intercept.

    Args:
        team_games: DataFrame with a "margin" column (team_score - opp_score)
            and a "win" column (1.0 / 0.5 / 0.0)

    Returns:
        (coef, intercept)
    """
    margin = team_games["margin"].to_numpy()
    win = team_games["win"].to_numpy()
    # scale margin so gradient descent converges without tuning per-league
    scale = margin.std() or 1.0
    x = margin / scale

    coef, intercept = 0.0, 0.0
    n = len(x)
    for _ in range(iterations):
        z = coef * x + intercept
        pred = 1.0 / (1.0 + np.exp(-z))
        error = pred - win
        coef -= learning_rate * (x @ error) / n
        intercept -= learning_rate * error.sum() / n

    return coef / scale, intercept


def win_probability(margin: float, coef: float, intercept: float) -> float:
    """P(win) for a given score margin, from a fitted model."""
    z = coef * margin + intercept
    return 1.0 / (1.0 + np.exp(-z))


def _replacement_levels(box_scores: pd.DataFrame) -> pd.Series:
    """
    For every (position, week), the AVERAGE points scored by players at
    that position who did NOT start anywhere that week that week — a
    typical bench/waiver-level alternative, across all 12 teams' benches.

    This intentionally averages rather than takes the max. A first pass
    at this used the best bench score at each position/week as
    "replacement level," but checked against the real 2025 data that
    turned out to set an unrealistically high bar: the single best
    benched RB leaguewide in an average week (23.7 pts) actually beat
    the average STARTING RB that week (15.2 pts) — because a 12-team
    league's bench pool sometimes has a real stud parked behind a
    depth-chart logjam or on a bye, not a "replacement" in any
    meaningful sense. Averaging the whole bench pool instead lands well
    below the starter average (5.6 pts for RB), which is what
    "replacement level" is supposed to mean: unremarkable, freely
    available talent, not the best case you could hope to find.

    Falls back to that week's worst ACTUAL starter only when no bench
    player at that position exists at all that week.

    Returns:
        Series indexed by (position, week) -> replacement-level points
    """
    is_bench = box_scores["lineup_slot"].isin(NON_STARTING_SLOTS)
    bench_avg = box_scores[is_bench].groupby(["position", "week"])["points"].mean()
    worst_starter = box_scores[~is_bench].groupby(["position", "week"])["points"].min()
    return bench_avg.combine_first(worst_starter)


def compute_season_war(
    box_scores: pd.DataFrame, team_games: pd.DataFrame, coef: float, intercept: float
) -> pd.DataFrame:
    """
    Season WAR per player: sum, across every week that player was
    started, of (win prob with their actual score) - (win prob if a
    replacement-level player had been started in that slot instead).

    Args:
        box_scores: raw box_scores rows for the season, QB/RB/WR/TE only
        team_games: team-game rows from TEAM_GAMES_SQL (adds "margin"/"win")
        coef, intercept: fitted win-probability model

    Returns:
        DataFrame: player_id, player_name, position, weeks_started,
            total_points, season_war
    """
    replacement = _replacement_levels(box_scores).rename("replacement_points")

    started = box_scores[~box_scores["lineup_slot"].isin(NON_STARTING_SLOTS)].copy()
    # merge rather than a row-wise apply/lookup: also sidesteps a pandas
    # edge case where .apply() on an empty DataFrame returns an empty
    # DataFrame instead of an empty Series, breaking column assignment
    started = started.merge(
        replacement.reset_index(), on=["position", "week"], how="left"
    )

    scores = team_games.set_index(["season", "week", "team_id"])["team_score"]
    opp_scores = team_games.set_index(["season", "week", "team_id"])["opp_score"]

    def _weekly_war(row) -> float:
        key = (row["season"], row["week"], row["team_id"])
        if key not in scores.index:
            return 0.0  # bye week / no opponent that week
        team_actual = scores.loc[key]
        opp = opp_scores.loc[key]
        team_replacement = team_actual - row["points"] + row["replacement_points"]
        return win_probability(team_actual - opp, coef, intercept) - win_probability(
            team_replacement - opp, coef, intercept
        )

    started["weekly_war"] = started.apply(_weekly_war, axis=1)

    agg = (
        started.groupby(["player_id", "player_name", "position"])
        .agg(
            weeks_started=("week", "count"),
            total_points=("points", "sum"),
            season_war=("weekly_war", "sum"),
        )
        .reset_index()
    )
    return agg.sort_values("season_war", ascending=False)


def get_season_war(season: int, min_weeks: int = 1) -> pd.DataFrame:
    """
    Season WAR for every player started at least once, QB/RB/WR/TE only.
    Works for any draft_type — draft price isn't needed to compute this,
    only to plot it (see join_draft_price + war_price_regression).

    Raises SeasonNotReadyError if the current season hasn't reached
    LIVE_SEASON_ANALYSIS_MIN_WEEK yet (same gate as draft ROI / waiver).
    """
    conn = get_connection()
    check_season_ready(season, get_max_ingested_week(conn, season))

    box_scores = pd.read_sql(BOX_SCORES_SQL, conn, params={"season": season})
    team_games = pd.read_sql(TEAM_GAMES_SQL, conn, params={"season": season})
    conn.close()

    team_games["margin"] = team_games["team_score"] - team_games["opp_score"]
    team_games["win"] = np.select(
        [team_games["margin"] > 0, team_games["margin"] < 0], [1.0, 0.0], default=0.5
    )

    coef, intercept = fit_win_probability_model(team_games)
    war = compute_season_war(box_scores, team_games, coef, intercept)
    return war[war["weeks_started"] >= min_weeks]


def join_draft_price(war_df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Left-join draft bid_amount onto a season WAR table. Undrafted
    (waiver-only) players keep bid_amount = NaN rather than being dropped."""
    conn = get_connection()
    prices = pd.read_sql(DRAFT_PRICE_SQL, conn, params={"season": season})
    conn.close()
    return war_df.merge(prices, on="player_id", how="left")


def join_draft_order(war_df: pd.DataFrame, season: int) -> pd.DataFrame:
    """Left-join overall_pick_number onto a season WAR table — the
    snake-draft counterpart to join_draft_price, for the ranked-bar-by-
    draft-order view (x-axis = pick number, not price)."""
    conn = get_connection()
    order = pd.read_sql(DRAFT_ORDER_SQL, conn, params={"season": season})
    conn.close()
    return war_df.merge(order, on="player_id", how="left")


def war_price_regression(war_with_price: pd.DataFrame, position: str) -> dict:
    """
    Least-squares fit of season_war ~ bid_amount for one position,
    drafted players only. Returns slope, intercept, r2, n — used both to
    draw the trend line and to report how well price predicted value.
    """
    rows = war_with_price[
        (war_with_price["position"] == position) & war_with_price["bid_amount"].notna()
    ]
    x = rows["bid_amount"].to_numpy(dtype=float)
    y = rows["season_war"].to_numpy(dtype=float)
    if len(x) < 2:
        return {"slope": None, "intercept": None, "r2": None, "n": len(x)}

    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    ss_res = np.sum((y - predicted) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"slope": slope, "intercept": intercept, "r2": r2, "n": len(x)}
