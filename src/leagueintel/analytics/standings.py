"""
Standings analytics — regular season win/loss records and scoring for a season.
"""

import pandas as pd
from leagueintel.storage.database import get_connection

STANDINGS_MATCHUPS_SQL = """
    SELECT
        m.week,
        ht.owner_name AS home_manager,
        ht.team_name AS home_team_name,
        ht.standing AS home_standing,
        at.owner_name AS away_manager,
        at.team_name AS away_team_name,
        at.standing AS away_standing,
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


def _side_frame(df: pd.DataFrame, side: str, other_side: str) -> pd.DataFrame:
    """
    Build one manager-perspective slice (home or away) of the matchups
    frame. `standing` (ESPN's playoffSeed, this manager's regular-season
    seed) rides along if the source query provided it — SQL-backed data
    always has it (possibly null for an unseeded/not-yet-ingested team),
    but unit tests that hand-build a matchups DataFrame directly don't
    include it at all, so it's added as all-NaN rather than assumed present.
    """
    frame = df.rename(
        columns={
            f"{side}_manager": "manager",
            f"{side}_team_name": "team_name",
            f"{side}_score": "points_for",
            f"{other_side}_score": "points_against",
            f"{side}_standing": "standing",
        }
    )
    if "standing" not in frame.columns:
        frame["standing"] = pd.NA
    return frame[["manager", "team_name", "points_for", "points_against", "standing"]]


def compute_standings(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate regular season matchups into a standings table.

    Each matchup is split into one row per side (home and away), each
    from that manager's own perspective, then grouped by manager.

    Args:
        df: raw matchups with home_manager, home_team_name, away_manager,
            away_team_name, home_score, away_score, and optionally
            home_standing/away_standing (ESPN's own regular-season seed)

    Returns:
        DataFrame with columns: manager, team_name, wins, losses, ties,
        points_for, points_against, point_diff, standing — sorted by
        `standing` (ESPN's own computed seed) when every manager has one;
        otherwise falls back to wins desc, then points_for desc, since
        that's the best this codebase can derive on its own without it
        (e.g. for synthetic test fixtures with no live ESPN backing).
    """
    home = _side_frame(df, "home", "away")
    away = _side_frame(df, "away", "home")
    games = pd.concat([home, away], ignore_index=True)

    games["result"] = "tie"
    games.loc[games["points_for"] > games["points_against"], "result"] = "win"
    games.loc[games["points_for"] < games["points_against"], "result"] = "loss"

    standings = (
        games.groupby(["manager", "team_name"])
        .agg(
            wins=("result", lambda s: (s == "win").sum()),
            losses=("result", lambda s: (s == "loss").sum()),
            ties=("result", lambda s: (s == "tie").sum()),
            points_for=("points_for", "sum"),
            points_against=("points_against", "sum"),
            standing=("standing", "first"),
        )
        .reset_index()
    )
    standings["point_diff"] = standings["points_for"] - standings["points_against"]

    if standings["standing"].notna().all():
        return standings.sort_values("standing", ascending=True).reset_index(drop=True)
    return standings.sort_values(
        ["wins", "points_for"], ascending=[False, False]
    ).reset_index(drop=True)


def is_median_scoring_enabled(season: int) -> bool:
    """Whether ESPN's "Bonus Wins and Losses" rule was active for a season."""
    conn = get_connection()
    row = conn.execute(
        "SELECT median_scoring FROM season_settings WHERE season = ?", (season,)
    ).fetchone()
    conn.close()
    return bool(row[0]) if row else False


def compute_median_scoring_bonus(df: pd.DataFrame) -> pd.DataFrame:
    """
    ESPN's "Bonus Wins and Losses" rule: each week, a team scoring above
    that week's league median earns a bonus win; below earns a bonus
    loss; exactly at the median (only possible with an odd team count)
    is a bonus tie. This needs every team's score for the week, not just
    their own matchup, so it melts the raw matchups into one row per
    team per week — kept separate from compute_standings, which only
    ever sees one matchup (two teams) at a time.

    Args:
        df: raw matchups with week, home_manager, away_manager,
            home_score, away_score (see STANDINGS_MATCHUPS_SQL)

    Returns:
        DataFrame with columns: manager, bonus_wins, bonus_losses, bonus_ties
    """
    home = df.rename(columns={"home_manager": "manager", "home_score": "points_for"})[
        ["week", "manager", "points_for"]
    ]
    away = df.rename(columns={"away_manager": "manager", "away_score": "points_for"})[
        ["week", "manager", "points_for"]
    ]
    weekly = pd.concat([home, away], ignore_index=True)

    weekly["week_median"] = weekly.groupby("week")["points_for"].transform("median")
    weekly["bonus_result"] = "tie"
    weekly.loc[weekly["points_for"] > weekly["week_median"], "bonus_result"] = "win"
    weekly.loc[weekly["points_for"] < weekly["week_median"], "bonus_result"] = "loss"

    return (
        weekly.groupby("manager")
        .agg(
            bonus_wins=("bonus_result", lambda s: (s == "win").sum()),
            bonus_losses=("bonus_result", lambda s: (s == "loss").sum()),
            bonus_ties=("bonus_result", lambda s: (s == "tie").sum()),
        )
        .reset_index()
    )


def get_standings(season: int) -> pd.DataFrame:
    """
    Fetch and compute the regular season standings for a season.

    If the season had ESPN's median-scoring rule enabled, adds
    bonus_wins/bonus_losses/bonus_ties columns — kept separate from the
    head-to-head wins/losses/ties so both records stay visible. Sort
    order needs no special handling for this: it already sorts by
    ESPN's own `standing`, which already factors bonus wins/losses into
    the official seed server-side.
    """
    matchups = get_regular_season_matchups(season)
    standings = compute_standings(matchups)

    if is_median_scoring_enabled(season):
        bonus = compute_median_scoring_bonus(matchups)
        standings = standings.merge(bonus, on="manager", how="left")

    return standings
