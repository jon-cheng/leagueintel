# tests/analytics/test_consolation.py
import sqlite3
import pytest
from leagueintel.storage.database import create_tables
from leagueintel.analytics import consolation


SEASON = 2024

TEAMS = [
    (1, SEASON, "Team Alpha", "ALPH", "Manager A"),
    (2, SEASON, "Team Bravo", "BRAV", "Manager B"),
    (3, SEASON, "Team Charlie", "CHAR", "Manager C"),
    (4, SEASON, "Team Delta", "DELT", "Manager D"),
    (5, SEASON, "Team Echo", "ECHO", "Manager E"),
    (6, SEASON, "Team Foxtrot", "FOXT", "Manager F"),
]


@pytest.fixture
def db_conn(tmp_path, monkeypatch):
    """
    File-backed sqlite db seeded with a small bracket, wired up as the
    connection consolation.py's queries run against. A real (if tiny)
    sqlite db keeps these tests honest about the actual SQL, not just
    the Python around it.

    Uses a temp file rather than ":memory:" because each consolation.py
    function opens and closes its own connection (mirroring production,
    where get_connection() opens a fresh connection per call) — an
    in-memory db would vanish as soon as the first connection closed.
    """
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    conn.executemany(
        "INSERT INTO teams (team_id, season, team_name, team_abbrev, owner_name) VALUES (?, ?, ?, ?, ?)",
        TEAMS,
    )
    conn.commit()

    monkeypatch.setattr(consolation, "get_connection", lambda: sqlite3.connect(db_path))
    yield conn
    conn.close()


def _set_final_standings(conn, standings_by_team_id: dict):
    """
    get_medal_standings/get_toilet_bowl_loser now read identity from
    teams.final_standing (ESPN's own post-season rank) rather than
    inferring it from game results — the shared TEAMS fixture leaves it
    NULL since most tests don't need it, so tests that do must set it
    explicitly to match the bracket they're constructing.
    """
    conn.executemany(
        "UPDATE teams SET final_standing = ? WHERE team_id = ? AND season = ?",
        [(rank, team_id, SEASON) for team_id, rank in standings_by_team_id.items()],
    )
    conn.commit()


def _insert_matchup(conn, week, home_id, away_id, home_score, away_score, matchup_type):
    conn.execute(
        """
        INSERT INTO matchups
            (season, week, home_team_id, away_team_id, home_score, away_score, matchup_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (SEASON, week, home_id, away_id, home_score, away_score, matchup_type),
    )
    conn.commit()


def test_get_medal_standings_identifies_first_second_third(db_conn):
    """
    A standard bracket: two semifinal winners meet in the championship,
    and the two semifinal losers meet for 3rd place. Confirms scores are
    read correctly and the higher scorer in each game is credited with
    the better placement.
    """
    # semifinal round (week 1)
    _insert_matchup(db_conn, 1, 1, 4, 100.0, 90.0, "WINNERS_BRACKET")  # A beats D
    _insert_matchup(db_conn, 1, 2, 3, 80.0, 110.0, "WINNERS_BRACKET")  # C beats B

    # championship + 3rd place game (week 2)
    _insert_matchup(db_conn, 2, 1, 3, 120.0, 100.0, "WINNERS_BRACKET")  # A beats C
    _insert_matchup(db_conn, 2, 4, 2, 95.0, 70.0, "WINNERS_CONSOLATION_LADDER")  # D beats B

    _set_final_standings(db_conn, {1: 1, 3: 2, 4: 3})  # A first, C second, D third

    standings = consolation.get_medal_standings(SEASON)

    assert standings["first"] == "Manager A"
    assert standings["second"] == "Manager C"
    assert standings["third"] == "Manager D"


def test_get_medal_standings_ignores_other_consolation_ladder_games(db_conn):
    """
    A 6-team bracket has both a 3rd place game and a 5th place game in
    the same final week, both tagged WINNERS_CONSOLATION_LADDER. The 3rd
    place lookup must pick the game between the actual semifinal losers,
    not just any consolation-ladder game from that week — a bug that
    grabbed the first match would silently report the wrong bronze
    medalist whenever a 5th place game also exists.
    """
    # semifinal round (week 1) — only A/D and B/C feed the championship;
    # E/F is a separate quarterfinal-loser game feeding the 5th place game
    _insert_matchup(db_conn, 1, 1, 4, 100.0, 90.0, "WINNERS_BRACKET")  # A beats D
    _insert_matchup(db_conn, 1, 2, 3, 80.0, 110.0, "WINNERS_BRACKET")  # C beats B

    # championship (week 2)
    _insert_matchup(db_conn, 2, 1, 3, 120.0, 100.0, "WINNERS_BRACKET")  # A beats C

    # 3rd place game: semifinal losers D and B
    _insert_matchup(db_conn, 2, 4, 2, 95.0, 70.0, "WINNERS_CONSOLATION_LADDER")  # D beats B
    # decoy 5th place game between unrelated teams E and F
    _insert_matchup(db_conn, 2, 5, 6, 60.0, 200.0, "WINNERS_CONSOLATION_LADDER")  # F beats E

    _set_final_standings(db_conn, {1: 1, 3: 2, 4: 3})  # A first, C second, D third

    standings = consolation.get_medal_standings(SEASON)

    assert standings["third"] == "Manager D"


def test_get_consolation_ladder_winner_refuses_unfinished_ladder(db_conn):
    """
    Protects against crowning a ladder winner while the ladder is still
    being played. An unplayed game has NULL scores; NaN fails the "<"
    check, so the away team used to be recorded as the loser and the home
    team declared winner before the final was played. The page already
    catches ValueError for "not available yet", so raise instead.
    """
    ladder = "LOSERS_CONSOLATION_LADDER"
    _insert_matchup(db_conn, 15, 1, 2, 110.0, 90.0, ladder)  # A beats B
    _insert_matchup(db_conn, 15, 3, 4, 105.0, 95.0, ladder)  # C beats D
    _insert_matchup(db_conn, 16, 1, 3, None, None, ladder)   # final: not played yet

    with pytest.raises(ValueError, match="not finished"):
        consolation.get_consolation_ladder_winner(SEASON)


LADDER = "LOSERS_CONSOLATION_LADDER"


def _play_full_ladder(conn):
    """
    A complete two-round ladder for the four non-playoff teams: C and E win
    round one; in the final week C stays undefeated (ladder winner) and D
    loses again (last place).
    """
    _insert_matchup(conn, 15, 3, 4, 110.0, 90.0, LADDER)  # C beats D
    _insert_matchup(conn, 15, 5, 6, 100.0, 95.0, LADDER)  # E beats F
    _insert_matchup(conn, 16, 3, 5, 120.0, 80.0, LADDER)  # C beats E
    _insert_matchup(conn, 16, 4, 6, 70.0, 85.0, LADDER)   # F beats D


def _live_season_final_standings(conn):
    """ESPN reports final_standing = 0 for every team until the season ends — not NULL."""
    _set_final_standings(conn, {team_id: 0 for team_id, *_ in TEAMS})


def test_ladder_winner_waits_for_season_to_finish(db_conn):
    """
    Protects against crowning a ladder winner a week early. Overnight after
    the second-to-last week's games end, every ingested ladder game is
    played but the final week isn't ingested yet (ESPN hasn't advanced
    current_week). Judging by the ladder data alone, that window returned
    a premature winner (with the wrong game shown as "the final") in a
    replay of 2019, and a misleading data error in 2023/2025.
    """
    _play_full_ladder(db_conn)
    _live_season_final_standings(db_conn)

    with pytest.raises(ValueError, match="not finished"):
        consolation.get_consolation_ladder_winner(SEASON)


def test_toilet_bowl_loser_waits_for_season_to_finish(db_conn):
    """
    Protects against naming an arbitrary team last place mid-playoffs.
    final_standing is 0 (not NULL) during the live season, so an
    "IS NOT NULL" check let it through and the highest of twelve zeros
    was picked as last place once ladder games existed.
    """
    _play_full_ladder(db_conn)
    _live_season_final_standings(db_conn)

    with pytest.raises(ValueError, match="not finished"):
        consolation.get_toilet_bowl_loser(SEASON)


def test_ladder_winner_and_toilet_bowl_once_season_finished(db_conn):
    """Protects real answers from the gate: once ESPN sets final ranks, both functions return results."""
    _play_full_ladder(db_conn)
    _set_final_standings(db_conn, {1: 1, 2: 2, 3: 3, 5: 4, 6: 5, 4: 6})  # D last

    ladder = consolation.get_consolation_ladder_winner(SEASON)
    assert (ladder["winner"], ladder["winner_score"], ladder["opponent"]) == ("Manager C", 120.0, "Manager E")

    toilet = consolation.get_toilet_bowl_loser(SEASON)
    assert (toilet["last_place"], toilet["last_place_score"], toilet["opponent"]) == ("Manager D", 70.0, "Manager F")
