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
    matchups = get_consolation_matchups(season)
    weeks = sorted(matchups["week"].unique())

    # count losses per manager across all rounds except final
    loss_count = {}
    for week in weeks[:-1]:
        week_games = matchups[matchups["week"] == week]
        for _, game in week_games.iterrows():
            if game["home_score"] < game["away_score"]:
                loser = game["home_owner"]
            else:
                loser = game["away_owner"]
            loss_count[loser] = loss_count.get(loser, 0) + 1

    # team with most losses = the one destined for last place game
    most_losses_team = max(loss_count, key=loss_count.get)

    print(f"loss counts: {loss_count}")
    print(f"most losses team: {most_losses_team}")

    # find their final week game
    final_games = matchups[matchups["week"] == weeks[-1]]
    last_place_game = final_games[
        (final_games["home_owner"] == most_losses_team)
        | (final_games["away_owner"] == most_losses_team)
    ]

    if last_place_game.empty:
        raise ValueError(
            f"Could not find last place game for {most_losses_team} in {season}"
        )

    game = last_place_game.iloc[0]

    if game["home_score"] < game["away_score"]:
        loser, loser_score = game["home_owner"], game["home_score"]
        winner, winner_score = game["away_owner"], game["away_score"]
    else:
        loser, loser_score = game["away_owner"], game["away_score"]
        winner, winner_score = game["home_owner"], game["home_score"]

    return {
        "season": season,
        "last_place": loser,
        "last_place_score": loser_score,
        "opponent": winner,
        "opponent_score": winner_score,
    }


def get_arbys_winner(season: int) -> dict:
    """
    Arby's winner = winner of the 7 vs 8 seed game in the
    final consolation week. Best finisher among non-playoff teams.
    Identified as the team with the most WINS in the consolation
    bracket prior to the final week — inverse of toilet bowl logic.
    """
    matchups = get_consolation_matchups(season)
    weeks = sorted(matchups["week"].unique())

    # count wins per manager across all rounds except final
    win_count = {}
    for week in weeks[:-1]:
        week_games = matchups[matchups["week"] == week]
        for _, game in week_games.iterrows():
            if game["home_score"] > game["away_score"]:
                winner = game["home_owner"]
            else:
                winner = game["away_owner"]
            win_count[winner] = win_count.get(winner, 0) + 1

    # team with most wins = destined for the arby's game
    most_wins_team = max(win_count, key=win_count.get)

    # find their final week game
    final_games = matchups[matchups["week"] == weeks[-1]]
    arbys_game = final_games[
        (final_games["home_owner"] == most_wins_team)
        | (final_games["away_owner"] == most_wins_team)
    ]

    if arbys_game.empty:
        raise ValueError(f"Could not find Arby's game for {most_wins_team} in {season}")

    game = arbys_game.iloc[0]

    if game["home_score"] > game["away_score"]:
        winner, winner_score = game["home_owner"], game["home_score"]
        loser, loser_score = game["away_owner"], game["away_score"]
    else:
        winner, winner_score = game["away_owner"], game["away_score"]
        loser, loser_score = game["home_owner"], game["home_score"]

    return {
        "season": season,
        "arbys_winner": winner,
        "winner_score": winner_score,
        "opponent": loser,
        "loser_score": loser_score,
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
