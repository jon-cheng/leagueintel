# tests/analytics/test_standings.py
import pandas as pd
from leagueintel.analytics.standings import compute_standings


def _matchup(home_manager, away_manager, home_score, away_score):
    return {
        "home_manager": home_manager,
        "away_manager": away_manager,
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
