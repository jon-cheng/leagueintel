"""
Standings analytics — regular season win/loss records and scoring for a season.
"""

import pandas as pd
from leagueintel.storage.database import get_connection

STANDINGS_MATCHUPS_SQL = """
    SELECT
        ht.owner_name AS home_manager,
        at.owner_name AS away_manager,
        m.home_score,
        m.away_score
    FROM matchups m
    JOIN teams ht ON m.home_team_id = ht.team_id AND m.season = ht.season
    JOIN teams at ON m.away_team_id = at.team_id AND m.season = at.season
    WHERE m.matchup_type = 'NONE'
    AND m.season = :season
"""


def get_regular_season_matchups(season: int) -> pd.DataFrame:
    """Fetch regular season matchups with manager names for both sides."""
    conn = get_connection()
    df = pd.read_sql(STANDINGS_MATCHUPS_SQL, conn, params={"season": season})
    conn.close()
    return df


def compute_standings(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate regular season matchups into a standings table.

    Each matchup is split into one row per side (home and away), each
    from that manager's own perspective, then grouped by manager.

    Args:
        df: raw matchups with home_manager, away_manager, home_score, away_score

    Returns:
        DataFrame with columns: manager, wins, losses, ties, points_for,
        points_against, point_diff — sorted by wins desc, then points_for desc.
    """
    home = df.rename(
        columns={
            "home_manager": "manager",
            "home_score": "points_for",
            "away_score": "points_against",
        }
    )[["manager", "points_for", "points_against"]]
    away = df.rename(
        columns={
            "away_manager": "manager",
            "away_score": "points_for",
            "home_score": "points_against",
        }
    )[["manager", "points_for", "points_against"]]
    games = pd.concat([home, away], ignore_index=True)

    games["result"] = "tie"
    games.loc[games["points_for"] > games["points_against"], "result"] = "win"
    games.loc[games["points_for"] < games["points_against"], "result"] = "loss"

    standings = (
        games.groupby("manager")
        .agg(
            wins=("result", lambda s: (s == "win").sum()),
            losses=("result", lambda s: (s == "loss").sum()),
            ties=("result", lambda s: (s == "tie").sum()),
            points_for=("points_for", "sum"),
            points_against=("points_against", "sum"),
        )
        .reset_index()
    )
    standings["point_diff"] = standings["points_for"] - standings["points_against"]

    return standings.sort_values(
        ["wins", "points_for"], ascending=[False, False]
    ).reset_index(drop=True)


def get_standings(season: int) -> pd.DataFrame:
    """Fetch and compute the regular season standings for a season."""
    matchups = get_regular_season_matchups(season)
    return compute_standings(matchups)
