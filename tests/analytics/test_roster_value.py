# tests/analytics/test_roster_value.py
import pandas as pd
from leagueintel.analytics.roster_value import compute_roster_value_scores


def _box_score(player_id, team_id, week, points, position="RB", season=2024):
    return {
        "player_id": player_id,
        "team_id": team_id,
        "season": season,
        "week": week,
        "points": points,
        "position": position,
    }


def test_compute_roster_value_scores_attaches_acquisition_type():
    """
    roster_value's whole point over waiver.py is spanning every
    acquisition type — the output must carry acquisition_type through so
    callers can tell a drafted player's stint from a waiver pickup's.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "DRAFT",
          "acquisition_week": 1, "drop_week": 18}]
    )
    box_scores = pd.DataFrame([_box_score(100, 1, w, 10) for w in range(1, 9)])
    players = pd.DataFrame([{"player_id": 100, "player_name": "First Rounder"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_roster_value_scores(stints, box_scores, players, teams)

    assert len(result) == 1
    assert result.iloc[0]["acquisition_type"] == "DRAFT"
    assert "value_score" in result.columns
    assert "waiver_score" not in result.columns


def test_compute_roster_value_scores_excludes_drafted_and_cut_before_week1():
    """
    Regression target for the Quinshon Judkins case: a player drafted and
    dropped before Week 1 (acquisition_week == drop_week == 1) must
    produce zero contribution — not a 0-week scored row.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "DRAFT",
          "acquisition_week": 1, "drop_week": 1}]
    )
    box_scores = pd.DataFrame(
        columns=["player_id", "team_id", "season", "week", "points", "position"]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Cut Before Week 1"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_roster_value_scores(stints, box_scores, players, teams)

    assert result.empty
    assert list(result.columns) == [
        "player_name", "team_name", "owner_name", "position",
        "acquisition_type", "acquisition_week", "num_weeks",
        "total_points", "value_score",
    ]
