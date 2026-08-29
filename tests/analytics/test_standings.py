# tests/analytics/test_standings.py
import sqlite3

import pandas as pd
import pytest

from leagueintel.analytics import standings
from leagueintel.analytics.standings import compute_median_scoring_bonus, compute_standings
from leagueintel.storage.database import create_tables


TEAM_NAME = {
    "Manager A": "Team Alpha",
    "Manager B": "Team Bravo",
    "Manager C": "Team Charlie",
    "Manager D": "Team Delta",
}


def _matchup(home_manager, away_manager, home_score, away_score, week=1):
    return {
        "week": week,
        "home_manager": home_manager,
        "home_team_name": TEAM_NAME[home_manager],
        "away_manager": away_manager,
        "away_team_name": TEAM_NAME[away_manager],
        "home_score": home_score,
        "away_score": away_score,
    }


def test_compute_standings_counts_wins_losses_ties_from_both_sides():
    """
    Each matchup must credit both the home and away manager with a game.
    A bug that only processed the home side would leave away-only
    managers (or an away win) missing from the standings entirely.
    """
    df = pd.DataFrame(
        [
            _matchup("Manager A", "Manager B", 120.0, 100.0),  # Manager A wins home
            _matchup("Manager B", "Manager A", 110.0, 90.0),  # Manager B wins home
            _matchup("Manager A", "Manager B", 100.0, 100.0),  # tie
        ]
    )
    result = compute_standings(df).set_index("manager")

    assert result.loc["Manager A", "wins"] == 1
    assert result.loc["Manager A", "losses"] == 1
    assert result.loc["Manager A", "ties"] == 1
    assert result.loc["Manager B", "wins"] == 1
    assert result.loc["Manager B", "losses"] == 1
    assert result.loc["Manager B", "ties"] == 1


def test_compute_standings_points_for_against_and_diff():
    """
    points_for/points_against must accumulate from the manager's own
    perspective regardless of home/away, and point_diff is simply
    their difference — protects against swapping PF/PA for away teams.
    """
    df = pd.DataFrame(
        [
            _matchup("Manager A", "Manager B", 120.0, 100.0),
            _matchup("Manager B", "Manager A", 80.0, 90.0),
        ]
    )
    result = compute_standings(df).set_index("manager")

    assert result.loc["Manager A", "points_for"] == 210.0
    assert result.loc["Manager A", "points_against"] == 180.0
    assert result.loc["Manager A", "point_diff"] == 30.0


def test_compute_standings_sorted_by_wins_then_points_for():
    """
    Tiebreak is points_for, not point_diff — deliberately construct a case
    where the two disagree (Manager C has the better diff but Manager A
    has the higher points_for) so a bug that sorted by diff instead of
    points_for would be caught rather than passing by coincidence.
    """
    df = pd.DataFrame(
        [
            _matchup("Manager A", "Manager B", 200.0, 190.0),  # PF 200, diff +10
            _matchup("Manager C", "Manager D", 150.0, 100.0),  # PF 150, diff +50
        ]
    )
    result = compute_standings(df)
    assert list(result["manager"])[:2] == ["Manager A", "Manager C"]


def test_compute_standings_includes_team_name_as_second_column():
    """
    team_name rides along with manager (one team per manager per season)
    so the Season Overview page can show it beside the manager — protects
    against a bug that drops team_name during the groupby/aggregate step.
    """
    df = pd.DataFrame(
        [
            _matchup("Manager A", "Manager B", 120.0, 100.0),
        ]
    )
    result = compute_standings(df)

    assert list(result.columns)[:2] == ["manager", "team_name"]
    assert result.set_index("manager").loc["Manager A", "team_name"] == "Team Alpha"
    assert result.set_index("manager").loc["Manager B", "team_name"] == "Team Bravo"


def test_median_scoring_bonus_splits_above_and_below_the_week_median():
    """
    ESPN's "Bonus Wins and Losses" rule: a team scoring above the whole
    league's median for that week gets a bonus win, below gets a bonus
    loss — evaluated against every team's score that week, not just
    their own opponent's, so this needs a week with more than one
    matchup to be a meaningful test at all.
    """
    df = pd.DataFrame(
        [
            _matchup("Manager A", "Manager B", 100.0, 90.0, week=1),  # median 85
            _matchup("Manager C", "Manager D", 80.0, 70.0, week=1),
        ]
    )
    result = compute_median_scoring_bonus(df).set_index("manager")

    assert result.loc["Manager A", "bonus_wins"] == 1
    assert result.loc["Manager B", "bonus_wins"] == 1
    assert result.loc["Manager C", "bonus_losses"] == 1
    assert result.loc["Manager D", "bonus_losses"] == 1


def test_median_scoring_bonus_ties_at_exact_median():
    """
    With an even team count, the statistical median falls between two
    real scores, so no team can land exactly on it. With an odd count
    (or a tied score), a team's score can equal the median exactly —
    that's a bonus tie, not an arbitrary win or loss.
    """
    df = pd.DataFrame(
        [
            _matchup("Manager A", "Manager B", 100.0, 90.0, week=1),  # median 90
            _matchup("Manager C", "Manager D", 80.0, 90.0, week=1),
        ]
    )
    result = compute_median_scoring_bonus(df).set_index("manager")

    assert result.loc["Manager A", "bonus_wins"] == 1
    assert result.loc["Manager B", "bonus_ties"] == 1
    assert result.loc["Manager D", "bonus_ties"] == 1
    assert result.loc["Manager C", "bonus_losses"] == 1


def test_median_scoring_bonus_accumulates_across_multiple_weeks():
    """
    Each week's median is computed independently — a bug that used one
    global median across all weeks (instead of per-week) would give the
    wrong bonus record whenever scoring levels differ week to week.
    """
    df = pd.DataFrame(
        [
            _matchup("Manager A", "Manager B", 100.0, 90.0, week=1),  # median 85
            _matchup("Manager C", "Manager D", 80.0, 70.0, week=1),
            _matchup("Manager A", "Manager C", 30.0, 90.0, week=2),  # median 95
            _matchup("Manager B", "Manager D", 100.0, 110.0, week=2),
        ]
    )
    result = compute_median_scoring_bonus(df).set_index("manager")

    # Manager A: week1 win (100>85), week2 loss (30<95)
    assert result.loc["Manager A", "bonus_wins"] == 1
    assert result.loc["Manager A", "bonus_losses"] == 1


@pytest.fixture
def db_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    monkeypatch.setattr(standings, "get_connection", lambda: sqlite3.connect(db_path))
    yield conn
    conn.close()


def test_is_median_scoring_enabled_reflects_season_settings(db_conn):
    """
    A season's rules can change year to year (this league added median
    scoring for 2026) — the flag must be looked up per season, not
    assumed constant across a league's history.
    """
    db_conn.execute(
        "INSERT INTO season_settings (season, median_scoring) VALUES (2025, 0), (2026, 1)"
    )
    db_conn.commit()

    assert standings.is_median_scoring_enabled(2025) is False
    assert standings.is_median_scoring_enabled(2026) is True


def test_is_median_scoring_enabled_defaults_false_for_unseen_season(db_conn):
    """A season never ingested into season_settings must not crash or default to True."""
    assert standings.is_median_scoring_enabled(1999) is False
