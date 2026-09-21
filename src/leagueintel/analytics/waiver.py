# src/leagueintel/analytics/waiver.py
"""
Waiver wire analytics — position-normalized percentile scoring for
waiver-only pickups.

Thin wrapper around stint_scoring.compute_stint_scores: waiver-specific
behavior is just the stint source (waiver_stints, so drafted players are
excluded) and top_n_weeks == min_weeks == TOP_N_WEEKS (config.py) — only
established pickups with a full sample are ranked. See stint_scoring.py
for the shared percentile methodology, and roster_value.py for the
generalized version covering every acquisition type with a relaxed
eligibility floor.

Stint boundaries (who was on which team, and when) come from the
waiver_stints SQL view — matching add/drop transactions into date ranges
is naturally a join and stays in SQL. Everything downstream (picking each
stint's best weeks, building the comparison population, scoring) is pandas.
"""

import pandas as pd
from leagueintel.storage.database import get_connection, get_max_ingested_week
from leagueintel.analytics.availability import check_season_ready
from leagueintel.analytics.stint_scoring import compute_stint_scores, compute_stint_scores_with_population
from leagueintel.config import TOP_N_WEEKS, DEFAULT_MAX_WEEK

WAIVER_STINTS_SQL = "SELECT * FROM waiver_stints WHERE season = :season"

BOX_SCORES_SQL = """
    SELECT player_id, team_id, season, week, points, position
    FROM box_scores
    WHERE season = :season
    AND position NOT IN ('K', 'D/ST')
"""

TEAMS_SQL = "SELECT team_id, season, team_name, owner_name FROM teams WHERE season = :season"

PLAYERS_SQL = "SELECT player_id, full_name AS player_name FROM players"

ROSTER_STINTS_SQL = "SELECT * FROM roster_stints WHERE season = :season"

# Priced acquisitions only — WAIVER (FAAB bid) and DRAFT (auction bid).
# FREEAGENT and TRADE have no per-player price in this league, so they're
# simply left unpriced (see compute_acquisition_history) rather than
# queried here.
ACQUISITION_BIDS_SQL = """
    SELECT tm.player_id, tm.to_team_id AS team_id, t.transaction_type,
           t.scoring_period_id AS week, t.bid_amount
    FROM transaction_moves tm
    JOIN transactions t ON tm.transaction_id = t.id
    WHERE t.season = :season
    AND t.status = 'EXECUTED'
    AND (
        (t.transaction_type = 'WAIVER' AND tm.item_type = 'ADD')
        OR (t.transaction_type = 'DRAFT' AND tm.item_type = 'DRAFT')
    )
    AND tm.player_id > 0
"""

ACQUISITION_TYPE_LABELS = {
    "DRAFT": "Draft",
    "WAIVER": "Waiver",
    "FREEAGENT": "Free Agent",
    "TRADE": "Trade",
}

RESULT_COLUMNS = [
    "player_name",
    "team_name",
    "owner_name",
    "position",
    "acquisition_week",
    "num_weeks",
    "total_points",
    "weeks",
    "median_total_points",
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
      player_name, team_name, owner_name, position, acquisition_week,
      num_weeks, total_points, weeks, median_total_points, waiver_score

    weeks: chronologically-sorted list of the week numbers that made up
    the player's best num_weeks (their top scoring weeks, pooled across
    every stint this manager had with them) — the transparency companion
    to waiver_score, showing exactly which weeks were counted.
    median_total_points: the comparison field's median TOTAL points over
    those same weeks — deliberately left as a raw total (not converted to
    PPG), since it's already on the exact same basis waiver_score itself
    compares against: if total_points is above this median, more than
    half the field scored less, i.e. waiver_score >= ~50.
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


def get_waiver_scores_with_population(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Same as get_waiver_scores, but also returns the raw comparison
    population behind each score — for a transparency drilldown (e.g. a
    beeswarm of every comparison player's total), not just the aggregated
    median_total_points.

    Returns (scores, population):
      scores: same rows as get_waiver_scores, but keeps player_id, team_id,
          acquisition_type (dropped from get_waiver_scores' own
          RESULT_COLUMNS) so callers can join a selected row to its slice
          of population.
      population: see stint_scoring.compute_stint_scores_with_population.

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

    return compute_stint_scores_with_population(
        stints, box_scores, players, teams,
        top_n_weeks=TOP_N_WEEKS, min_weeks=TOP_N_WEEKS,
    )


def _week_range(acquisition_week: int, drop_week: int, max_ingested_week: int) -> str:
    """
    "Wk N" for a single week, "Wk N-M" for a range, "Wk N-present" for a
    stint still open in a season that hasn't finished yet.

    drop_week <= acquisition_week (duration_weeks == 0 — a same-week
    add/cut) has no real second week, so it's shown as the single
    acquisition week, not a backwards range.

    drop_week is the SAME team's next departure, or 18 (roster_stints'
    sentinel for "never dropped") if still held. For a COMPLETED season
    (max_ingested_week >= DEFAULT_MAX_WEEK), that sentinel really does
    mean "held through week 17" — display it as such. But for a season
    still IN PROGRESS, the sentinel only means "not dropped as of the
    most recently ingested week" — displaying "-17" there would claim
    knowledge of the season's outcome we don't actually have yet (e.g.
    showing "Wk 1-17" for a player drafted this year while we're only
    in week 2). "present" makes that open-endedness explicit instead.
    """
    if drop_week <= acquisition_week:
        return f"Wk {acquisition_week}"
    if drop_week >= 18 and max_ingested_week < DEFAULT_MAX_WEEK:
        return f"Wk {acquisition_week}-present"
    end = min(drop_week, 18) - 1
    if end == acquisition_week:
        return f"Wk {acquisition_week}"
    return f"Wk {acquisition_week}-{end}"


def compute_acquisition_history(
    stints: pd.DataFrame, bids: pd.DataFrame, teams: pd.DataFrame, max_ingested_week: int
) -> pd.DataFrame:
    """
    Format each player's full-season roster history — every stint, by
    EVERY manager and acquisition type (draft, waiver, free agent,
    trade), not just the manager a given waiver_score row is scoring —
    as one chronological display string per player_id. Pure function —
    no DB access. Generalizes the earlier waiver-only bid history to
    every acquisition path, matching roster_stints/roster_value.py's
    scope rather than waiver_stints' narrower one.

    Args:
        stints: one row per roster stint — player_id, team_id, season,
            acquisition_type, acquisition_week, drop_week (from the
            roster_stints view — ALL acquisition types, unlike
            waiver_stints)
        bids: player_id, team_id, transaction_type, week, bid_amount —
            one row per EXECUTED priced acquisition (WAIVER ADD or DRAFT
            pick; see ACQUISITION_BIDS_SQL). FREEAGENT/TRADE stints have
            no matching row here and so show no price.
        teams: team_id, season, team_name, owner_name
        max_ingested_week: how much of the season has actually been
            ingested — see _week_range for why a still-open stint needs
            this to avoid claiming a final week we don't know yet.

    Returns DataFrame with columns: player_id, history
      history: "manager: (Type, $price, Wk N-M)" entries — price omitted
      when not applicable, "Wk N-present" for a stint still open in an
      unfinished season — chronological by acquisition_week, joined
      with "; " — e.g.
      "Daniel Corbett: (Waiver, $8, Wk 3-9); Calvin Cotton: (Waiver, $7, Wk 10-17)"
    """
    if stints.empty:
        return pd.DataFrame(columns=["player_id", "history"])

    # bids' transaction_type (WAIVER/DRAFT) maps 1:1 to acquisition_type
    # here — matching on it (not just player/team/week) avoids
    # misattributing a price if a team both drafted AND waiver-added the
    # same player in the same week (acquisition_week == 1 for drafts).
    priced = stints.merge(
        bids.rename(columns={"week": "acquisition_week", "transaction_type": "acquisition_type"}),
        on=["player_id", "team_id", "acquisition_week", "acquisition_type"],
        how="left",
    )
    merged = priced.merge(teams[["team_id", "owner_name"]].drop_duplicates("team_id"), on="team_id")
    merged = merged.sort_values("acquisition_week")

    def _entry(row):
        parts = [ACQUISITION_TYPE_LABELS.get(row["acquisition_type"], row["acquisition_type"])]
        if pd.notna(row.get("bid_amount")):
            parts.append(f"${row['bid_amount']:.0f}")
        parts.append(_week_range(row["acquisition_week"], row["drop_week"], max_ingested_week))
        return f"{row['owner_name']}: ({', '.join(parts)})"

    merged["entry"] = merged.apply(_entry, axis=1)
    return (
        merged.groupby("player_id")["entry"]
        .apply(lambda entries: "; ".join(entries))
        .reset_index(name="history")
    )


def get_acquisition_history(season: int) -> pd.DataFrame:
    """
    DB-facing wrapper around compute_acquisition_history — every
    player's full roster history for the season, one row per player_id.
    See compute_acquisition_history for the format.
    """
    conn = get_connection()
    max_ingested_week = get_max_ingested_week(conn, season)
    stints = pd.read_sql(ROSTER_STINTS_SQL, conn, params={"season": season})
    bids = pd.read_sql(ACQUISITION_BIDS_SQL, conn, params={"season": season})
    teams = pd.read_sql(TEAMS_SQL, conn, params={"season": season})
    conn.close()
    return compute_acquisition_history(stints, bids, teams, max_ingested_week)
