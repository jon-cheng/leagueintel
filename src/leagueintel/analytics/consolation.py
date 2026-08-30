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
    Last place = the team with the worst (highest) final_standing, ESPN's
    own post-season computed rank — authoritative, so unlike the old
    most-losses heuristic this doesn't need to guess who ends up last
    from partial ladder results. The final week's consolation-ladder game
    is only consulted afterward, to pull the opponent/scores for display.
    """
    conn = get_connection()
    last_place_row = pd.read_sql(
        """
        SELECT owner_name FROM teams
        WHERE season = :season AND final_standing IS NOT NULL
        ORDER BY final_standing DESC
        LIMIT 1
        """,
        conn,
        params={"season": season},
    )
    conn.close()

    if last_place_row.empty:
        raise ValueError(f"No final_standing data for season {season}")
    last_place_owner = last_place_row.iloc[0]["owner_name"]

    matchups = get_consolation_matchups(season)
    if matchups.empty:
        raise ValueError(f"No consolation ladder matchups ingested for season {season}")
    weeks = sorted(matchups["week"].unique())
    final_games = matchups[matchups["week"] == weeks[-1]]
    last_place_game = final_games[
        (final_games["home_owner"] == last_place_owner)
        | (final_games["away_owner"] == last_place_owner)
    ]

    if last_place_game.empty:
        raise ValueError(
            f"Could not find last place game for {last_place_owner} in {season}"
        )

    game = last_place_game.iloc[0]
    if game["home_owner"] == last_place_owner:
        last_place_score, opponent, opponent_score = (
            game["home_score"],
            game["away_owner"],
            game["away_score"],
        )
    else:
        last_place_score, opponent, opponent_score = (
            game["away_score"],
            game["home_owner"],
            game["home_score"],
        )

    return {
        "season": season,
        "last_place": last_place_owner,
        "last_place_score": last_place_score,
        "opponent": opponent,
        "opponent_score": opponent_score,
    }


def get_consolation_ladder_winner(season: int) -> dict:
    """
    Best finisher among non-playoff teams — winner of the consolation
    ladder's own top placement game (your league may call this "Arby's"
    or something else; that's a display-layer label, not this function's
    concern — see config.CONSOLATION_LADDER_WINNER_LABEL).

    In ESPN's consolation ladder, a win moves a team "up" and a loss
    moves it "down," and neither the top nor bottom slot can move
    further in that direction once reached (see the ESPN rules note in
    GENERALIZATION_PLAN.md step 4). That means a single loss anywhere in
    the ladder removes a team from top-slot contention for good — so the
    team occupying the top slot at the end must be the one and only team
    that never lost a single ladder game all season. This replaces the
    old "most wins before the final week" heuristic, which wasn't
    guaranteed to pick the same team in a bracket with byes.
    """
    matchups = get_consolation_matchups(season)
    if matchups.empty:
        raise ValueError(f"No consolation ladder matchups ingested for season {season}")
    weeks = sorted(matchups["week"].unique())

    losses = set()
    for _, game in matchups.iterrows():
        loser = game["home_owner"] if game["home_score"] < game["away_score"] else game["away_owner"]
        losses.add(loser)

    final_games = matchups[matchups["week"] == weeks[-1]]
    final_week_owners = pd.concat([final_games["home_owner"], final_games["away_owner"]])
    undefeated = [owner for owner in final_week_owners.unique() if owner not in losses]

    if len(undefeated) != 1:
        raise ValueError(
            f"Expected exactly one undefeated consolation-ladder team in the "
            f"{season} final week, found {undefeated}"
        )
    winner = undefeated[0]

    game_row = final_games[
        (final_games["home_owner"] == winner) | (final_games["away_owner"] == winner)
    ].iloc[0]
    if game_row["home_owner"] == winner:
        winner_score, opponent, opponent_score = (
            game_row["home_score"],
            game_row["away_owner"],
            game_row["away_score"],
        )
    else:
        winner_score, opponent, opponent_score = (
            game_row["away_score"],
            game_row["home_owner"],
            game_row["home_score"],
        )

    return {
        "season": season,
        "winner": winner,
        "winner_score": winner_score,
        "opponent": opponent,
        "opponent_score": opponent_score,
    }


def _get_championship_game(season: int) -> pd.Series:
    """Fetch the final-week WINNERS_BRACKET game (1st vs 2nd place)."""
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT
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
        WHERE m.matchup_type = 'WINNERS_BRACKET'
        AND m.season = :season
        AND m.week = (
            SELECT MAX(week) FROM matchups
            WHERE matchup_type = 'WINNERS_BRACKET' AND season = :season
        )
    """,
        conn,
        params={"season": season},
    )
    conn.close()

    if df.empty:
        raise ValueError(f"Could not find championship game for {season}")

    return df.iloc[0]


def _get_semifinal_losers(season: int) -> set[int]:
    """
    Team ids that lost in the semifinal round of the WINNERS_BRACKET
    (the round immediately before the championship). These two teams
    play each other for 3rd place.
    """
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT home_team_id, away_team_id, home_score, away_score
        FROM matchups
        WHERE matchup_type = 'WINNERS_BRACKET'
        AND season = :season
        AND week = (
            SELECT MAX(week) FROM matchups
            WHERE matchup_type = 'WINNERS_BRACKET' AND season = :season
        ) - 1
    """,
        conn,
        params={"season": season},
    )
    conn.close()

    losers = set()
    for _, game in df.iterrows():
        if game["home_score"] < game["away_score"]:
            losers.add(game["home_team_id"])
        else:
            losers.add(game["away_team_id"])
    return losers


def _get_third_place_game(season: int) -> pd.Series:
    """
    Fetch the final-week WINNERS_CONSOLATION_LADDER game between the
    two semifinal losers (the true 3rd place game, as opposed to any
    other consolation-ladder placement game in the same week).
    """
    semifinal_losers = _get_semifinal_losers(season)

    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT
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
        WHERE m.matchup_type = 'WINNERS_CONSOLATION_LADDER'
        AND m.season = :season
        AND m.week = (
            SELECT MAX(week) FROM matchups
            WHERE matchup_type = 'WINNERS_BRACKET' AND season = :season
        )
    """,
        conn,
        params={"season": season},
    )
    conn.close()

    third_place_game = df[
        df.apply(
            lambda g: {g["home_team_id"], g["away_team_id"]} == semifinal_losers,
            axis=1,
        )
    ]

    if third_place_game.empty:
        raise ValueError(f"Could not find 3rd place game for {season}")

    return third_place_game.iloc[0]


def _score_for(game: pd.Series, owner: str, context: str) -> float:
    if game["home_owner"] == owner:
        return game["home_score"]
    if game["away_owner"] == owner:
        return game["away_score"]
    raise ValueError(f"{owner!r} not found in {context}")


def get_medal_standings(season: int) -> dict:
    """
    1st/2nd/3rd place = teams with final_standing 1/2/3, ESPN's own
    post-season computed rank — authoritative, so this no longer infers
    identity from game results. The championship/3rd-place games are
    only consulted afterward, to pull each team's score for display.
    """
    conn = get_connection()
    top3 = pd.read_sql(
        """
        SELECT owner_name, final_standing FROM teams
        WHERE season = :season AND final_standing IN (1, 2, 3)
        ORDER BY final_standing
        """,
        conn,
        params={"season": season},
    )
    conn.close()

    if len(top3) != 3:
        raise ValueError(
            f"Expected 3 teams with final_standing 1-3 for season {season}, found {len(top3)}"
        )
    owner_by_rank = dict(zip(top3["final_standing"], top3["owner_name"]))
    first, second, third = owner_by_rank[1], owner_by_rank[2], owner_by_rank[3]

    champ_game = _get_championship_game(season)
    first_score = _score_for(champ_game, first, f"the {season} championship game")
    second_score = _score_for(champ_game, second, f"the {season} championship game")

    third_game = _get_third_place_game(season)
    third_score = _score_for(third_game, third, f"the {season} third place game")

    return {
        "season": season,
        "first": first,
        "first_score": first_score,
        "second": second,
        "second_score": second_score,
        "third": third,
        "third_score": third_score,
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
