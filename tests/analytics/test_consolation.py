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

    standings = consolation.get_medal_standings(SEASON)

    assert standings["third"] == "Manager D"
