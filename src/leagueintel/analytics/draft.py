"""
Draft analytics — ROI analysis for auction draft picks.
"""

import pandas as pd
from leagueintel.storage.database import get_connection, get_max_ingested_week
from leagueintel.config import MIN_WEEKS
from leagueintel.analytics.availability import check_season_ready

DRAFT_BOX_SCORES_SQL = """
    SELECT * FROM draft_box_scores WHERE season = :season
"""

# draft_box_scores excludes K and D/ST (not meaningful for the ROI plot's
# points-per-game analysis) — this mirrors that view's join but keeps every
# position, for the full Draft Selections table.
DRAFT_SELECTIONS_ALL_POSITIONS_SQL = """
    SELECT
        p.full_name AS player_name,
        t.bid_amount,
        t.season,
        tm.owner_name,
        tm.team_name,
        bs.position,
        bs.points,
        bs.lineup_slot,
        bs.week
    FROM transactions t
    JOIN transaction_moves mv ON t.id = mv.transaction_id
    JOIN players p ON mv.player_id = p.player_id
    JOIN teams tm ON t.team_id = tm.team_id AND t.season = tm.season
    JOIN box_scores bs
        ON mv.player_id = bs.player_id
        AND t.team_id = bs.team_id
        AND t.season = bs.season
    WHERE t.transaction_type = 'DRAFT'
    AND t.status = 'EXECUTED'
    AND mv.item_type = 'DRAFT'
    AND t.season = :season
"""

NON_STARTING_SLOTS = ["BE", "IR"]


def get_draft_roi(season: int, min_weeks: int = MIN_WEEKS) -> pd.DataFrame:
    """Fetch draft data and compute ROI metrics (QB/RB/WR/TE only).

    Raises SeasonNotReadyError if the current season hasn't reached
    LIVE_SEASON_ANALYSIS_MIN_WEEK yet.
    """
    conn = get_connection()
    check_season_ready(season, get_max_ingested_week(conn, season))
    df_raw = pd.read_sql(DRAFT_BOX_SCORES_SQL, conn, params={"season": season})
    conn.close()
    return compute_draft_roi(df_raw, min_weeks=min_weeks)


def get_draft_selections(season: int) -> pd.DataFrame:
    """
    Fetch every drafted player's box score performance, including K and D/ST
    — for the full Draft Selections table, not the position-limited ROI plot.
    """
    conn = get_connection()
    df_raw = pd.read_sql(
        DRAFT_SELECTIONS_ALL_POSITIONS_SQL, conn, params={"season": season}
    )
    conn.close()
    return compute_draft_roi(df_raw, min_weeks=0)


def compute_draft_roi(df: pd.DataFrame, min_weeks: int = MIN_WEEKS) -> pd.DataFrame:
    """
    Compute points per game started for each drafted player.
    Filter to players with at least min_weeks games started.

    "Started" means lineup_slot is an actual starting position —
    excludes bench (BE) and injured reserve (IR). Players who never
    started a game have no rows left after this exclusion, so they
    are absent regardless of min_weeks — pass min_weeks=0 to include
    every player with at least one start (e.g. for a full draft
    selections table, as opposed to the ROI plot's min-starts cutoff).

    Args:
        df: raw draft box scores DataFrame from draft_box_scores view
        min_weeks: minimum games started required to keep a player

    Returns:
        DataFrame with columns:
            player_name, bid_amount, owner_name, position,
            games_started, total_points, points_per_game
    """
    started = df[~df["lineup_slot"].isin(NON_STARTING_SLOTS)].copy()
    agg = (
        started.groupby(["player_name", "bid_amount", "owner_name", "position"])
        .agg(games_started=("week", "count"), total_points=("points", "sum"))
        .reset_index()
    )
    agg = agg[agg["games_started"] >= min_weeks]
    agg["points_per_game"] = (agg["total_points"] / agg["games_started"]).round(2)
    return agg.sort_values("points_per_game", ascending=False)
