import pandas as pd
from leagueintel.storage.database import get_connection


def get_regular_season_standings(season: int) -> pd.DataFrame:
    """
    Regular season standings sorted by wins then total points.
    This determines consolation seeding.
    """
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT
            t.team_id,
            t.owner_name,
            SUM(CASE
                WHEN m.home_team_id = t.team_id
                AND m.home_score > m.away_score THEN 1
                WHEN m.away_team_id = t.team_id
                AND m.away_score > m.home_score THEN 1
                ELSE 0 END) AS wins,
            SUM(CASE
                WHEN m.home_team_id = t.team_id
                AND m.home_score < m.away_score THEN 1
                WHEN m.away_team_id = t.team_id
                AND m.away_score < m.home_score THEN 1
                ELSE 0 END) AS losses,
            SUM(CASE
                WHEN m.home_team_id = t.team_id THEN m.home_score
                ELSE m.away_score END) AS total_points
        FROM teams t
        JOIN matchups m
            ON (m.home_team_id = t.team_id
                OR m.away_team_id = t.team_id)
            AND m.season = t.season
        WHERE t.season = :season
        AND m.matchup_type = 'NONE'
        AND m.away_team_id IS NOT NULL
        GROUP BY t.team_id, t.owner_name
        ORDER BY wins DESC, total_points DESC
    """,
        conn,
        params={"season": season},
    )
    conn.close()

    df["seed"] = range(1, len(df) + 1)
    return df


def get_consolation_matchups(season: int) -> pd.DataFrame:
    """Fetch all consolation ladder matchups with owner names."""
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT
            m.week,
            m.home_team_id,
            m.away_team_id,
            m.home_score,
            m.away_score,
            ht.owner_name AS home_owner,
            at.owner_name AS away_owner
        FROM matchups m
        JOIN teams ht
            ON m.home_team_id = ht.team_id
            AND m.season = ht.season
        JOIN teams at
            ON m.away_team_id = at.team_id
            AND m.season = at.season
        WHERE m.matchup_type = 'LOSERS_CONSOLATION_LADDER'
        AND m.season = :season
        ORDER BY m.week
    """,
        conn,
        params={"season": season},
    )
    conn.close()
    return df


def get_toilet_bowl_loser(season: int) -> dict:
    """
    Track losers through consolation bracket week by week.
    Teams that lose every round end up in the last place game.
    Toilet bowl loser = loser of the game between the two
    teams who lost in both week 15 AND week 16.
    """
    matchups = get_consolation_matchups(season)
    weeks = sorted(matchups["week"].unique())

    # week 1: find all losers
    round1_games = matchups[matchups["week"] == weeks[0]]
    round1_losers = set()
    for _, game in round1_games.iterrows():
        if game["home_score"] < game["away_score"]:
            round1_losers.add(game["home_owner"])
        else:
            round1_losers.add(game["away_owner"])

    # week 2: among round1 losers, find who lost again
    round2_games = matchups[matchups["week"] == weeks[1]]
    round2_losers = set()
    for _, game in round2_games.iterrows():
        home = game["home_owner"]
        away = game["away_owner"]
        # only care about games between round1 losers
        if home in round1_losers and away in round1_losers:
            if game["home_score"] < game["away_score"]:
                round2_losers.add(home)
            else:
                round2_losers.add(away)

    # week 3: find the game between the two teams
    # who lost in both round1 AND round2
    double_losers = round1_losers & round2_losers
    final_games = matchups[matchups["week"] == weeks[2]]

    last_place_game = final_games[
        (final_games["home_owner"].isin(double_losers))
        & (final_games["away_owner"].isin(double_losers))
    ]

    if last_place_game.empty:
        raise ValueError(f"Could not find last place game in {season}")

    game = last_place_game.iloc[0]

    if game["home_score"] < game["away_score"]:
        loser = game["home_owner"]
        loser_score = game["home_score"]
        winner = game["away_owner"]
        winner_score = game["away_score"]
    else:
        loser = game["away_owner"]
        loser_score = game["away_score"]
        winner = game["home_owner"]
        winner_score = game["home_score"]

    return {
        "season": season,
        "last_place": loser,
        "last_place_score": loser_score,
        "opponent": winner,
        "opponent_score": winner_score,
    }


def get_toilet_bowl_history(seasons: list[int]) -> pd.DataFrame:
    """Last place finisher across multiple seasons."""
    rows = []
    for season in seasons:
        try:
            result = get_toilet_bowl_loser(season)
            rows.append(result)
        except Exception as e:
            pass  # season may not have consolation data
    return pd.DataFrame(rows)
