# tests/analytics/test_waiver.py
import pandas as pd
from leagueintel.analytics.waiver import compute_waiver_scores


def _box_score(player_id, team_id, week, points, position="RB", season=2024):
    return {
        "player_id": player_id,
        "team_id": team_id,
        "season": season,
        "week": week,
        "points": points,
        "position": position,
    }


def test_compute_waiver_scores_percentile_against_comparison_pool():
    """
    Regression target for the SQL -> pandas port: with one waiver stint
    (player 100, weeks 1-8, 10 pts/week -> 80 total) and two comparison
    players at the same position over the same weeks (one who scored
    less, one who scored more), the percentile should be exactly 1/3
    (only the lower scorer counts as "scored less"). The query player's
    own rows are included in the comparison pool by design (mirrors the
    original SQL, which never excludes bs.player_id = pt.player_id) but
    can never count as "less than" itself, so it doesn't bias the score.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_week": 1, "drop_week": 18}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in range(1, 9)]
        + [_box_score(200, 2, w, 5) for w in range(1, 9)]
        + [_box_score(300, 3, w, 15) for w in range(1, 9)]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Waiver Wonder"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_waiver_scores(stints, box_scores, players, teams)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["player_name"] == "Waiver Wonder"
    assert row["total_points"] == 80
    assert row["num_weeks"] == 8
    assert row["waiver_score"] == round(100 / 3, 1)


def test_compute_waiver_scores_excludes_stints_under_min_weeks():
    """
    A stint with fewer than TOP_N_WEEKS (8) scored weeks has too small a
    sample to be meaningful and must be excluded entirely, not scored
    against a partial week count.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_week": 1, "drop_week": 6}]
    )
    box_scores = pd.DataFrame([_box_score(100, 1, w, 10) for w in range(1, 6)])
    players = pd.DataFrame([{"player_id": 100, "player_name": "Short Stint"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_waiver_scores(stints, box_scores, players, teams)

    assert result.empty
    assert list(result.columns) == [
        "player_name", "team_name", "owner_name", "position",
        "acquisition_week", "num_weeks", "total_points", "waiver_score",
    ]


def test_compute_waiver_scores_only_uses_weeks_on_roster():
    """
    Box scores outside [acquisition_week, drop_week) — e.g. before the
    player was added — must not leak into the stint's top-8 selection.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_week": 5, "drop_week": 18}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 100) for w in range(1, 5)]  # before acquisition — must be ignored
        + [_box_score(100, 1, w, 10) for w in range(5, 13)]  # 8 weeks on roster
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Late Add"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_waiver_scores(stints, box_scores, players, teams)

    assert result.iloc[0]["total_points"] == 80  # 8 weeks x 10, not inflated by the pre-add 100s
