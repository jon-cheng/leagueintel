"""
Head-to-head analytics — all-time regular season records between managers.
"""

import pandas as pd
from leagueintel.storage.database import get_connection
from leagueintel.config import ALL_SEASONS

H2H_MATCHUPS_SQL = """
    SELECT
        m.season,
        m.week,
        ht.owner_name AS home_manager,
        at.owner_name AS away_manager,
        m.home_score,
        m.away_score
    FROM matchups m
    JOIN teams ht ON m.home_team_id = ht.team_id AND m.season = ht.season
    JOIN teams at ON m.away_team_id = at.team_id AND m.season = at.season
    WHERE m.matchup_type = 'NONE'
    AND m.season BETWEEN :min_season AND :max_season
"""


def _last_name(owner_name: str) -> str:
    return owner_name.strip().split()[-1]


def get_h2h_matchups(seasons=ALL_SEASONS) -> pd.DataFrame:
    """Fetch regular season matchups with manager names for both sides."""
    conn = get_connection()
    df = pd.read_sql(
        H2H_MATCHUPS_SQL,
        conn,
        params={"min_season": min(seasons), "max_season": max(seasons)},
    )
    conn.close()
    return df


def compute_h2h_records(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate raw matchups into one row per unordered manager pair.

    manager_a is always the alphabetically-first (by last name) manager
    in the pair, so a rematch (either manager home or away) always rolls
    up into the same pair row.

    Args:
        df: raw matchups with home_manager, away_manager, home_score, away_score

    Returns:
        DataFrame with columns: manager_a, manager_b, wins_a, wins_b, ties
    """
    records = {}
    for row in df.itertuples():
        pair = tuple(sorted((row.home_manager, row.away_manager), key=_last_name))
        rec = records.setdefault(pair, {"wins_a": 0, "wins_b": 0, "ties": 0})

        a_score, b_score = (
            (row.home_score, row.away_score)
            if row.home_manager == pair[0]
            else (row.away_score, row.home_score)
        )
        if a_score > b_score:
            rec["wins_a"] += 1
        elif b_score > a_score:
            rec["wins_b"] += 1
        else:
            rec["ties"] += 1

    return pd.DataFrame(
        [{"manager_a": a, "manager_b": b, **rec} for (a, b), rec in records.items()]
    )


def build_h2h_matrix(records_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Pivot long-form head-to-head records into two full manager x manager
    matrices, ordered by last name: a "W-L-T" text matrix and a matching
    win-percentage matrix (ties excluded from the denominator).

    Both [A, B] and [B, A] are filled, each from that row manager's own
    perspective — a manager's win is their opponent's loss, so the two
    cells are complementary, not duplicates. The diagonal is blank/NaN.
    win_pct is NaN wherever the pair has no decided (non-tie) games,
    so it can be excluded from color scaling without being read as 0%.
    """
    managers = sorted(
        set(records_df["manager_a"]) | set(records_df["manager_b"]), key=_last_name
    )
    text_matrix = pd.DataFrame("", index=managers, columns=managers)
    pct_matrix = pd.DataFrame(float("nan"), index=managers, columns=managers)

    for row in records_df.itertuples():
        a, b = row.manager_a, row.manager_b
        text_matrix.loc[a, b] = f"{row.wins_a}-{row.wins_b}-{row.ties}"
        text_matrix.loc[b, a] = f"{row.wins_b}-{row.wins_a}-{row.ties}"

        decided = row.wins_a + row.wins_b
        if decided > 0:
            pct_matrix.loc[a, b] = row.wins_a / decided
            pct_matrix.loc[b, a] = row.wins_b / decided

    return text_matrix, pct_matrix


def get_h2h_matrix(seasons=ALL_SEASONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch and build the all-time head-to-head matrices (text, win_pct)."""
    matchups = get_h2h_matchups(seasons)
    records = compute_h2h_records(matchups)
    return build_h2h_matrix(records)
