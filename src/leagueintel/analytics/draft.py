"""
Draft analytics — ROI analysis for auction draft picks.
"""

import pandas as pd
from leagueintel.storage.database import get_connection
from leagueintel.config import MIN_WEEKS

DRAFT_BOX_SCORES_SQL = """
    SELECT * FROM draft_box_scores WHERE season = :season
"""

NON_STARTING_SLOTS = ["BE", "IR"]


def get_draft_roi(season: int) -> pd.DataFrame:
    """Fetch draft data and compute ROI metrics."""
    conn = get_connection()
    df_raw = pd.read_sql(DRAFT_BOX_SCORES_SQL, conn, params={"season": season})
    conn.close()
    return compute_draft_roi(df_raw)


def compute_draft_roi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute points per game started for each drafted player.
    Filter to players with at least MIN_WEEKS games started.

    "Started" means lineup_slot is an actual starting position —
    excludes bench (BE) and injured reserve (IR).

    Args:
        df: raw draft box scores DataFrame from draft_box_scores view

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
    agg = agg[agg["games_started"] >= MIN_WEEKS]
    agg["points_per_game"] = (agg["total_points"] / agg["games_started"]).round(2)
    return agg.sort_values("points_per_game", ascending=False)
