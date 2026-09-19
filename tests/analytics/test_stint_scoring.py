# tests/analytics/test_stint_scoring.py
import pandas as pd
from leagueintel.analytics.stint_scoring import compute_stint_scores


def _box_score(player_id, team_id, week, points, position="RB", season=2024):
    return {
        "player_id": player_id,
        "team_id": team_id,
        "season": season,
        "week": week,
        "points": points,
        "position": position,
    }


def test_compute_stint_scores_percentile_against_comparison_pool():
    """
    With one stint (player 100, weeks 1-8, 10 pts/week -> 80 total) and two
    comparison players at the same position over the same weeks (one who
    scored less, one who scored more), the percentile should be exactly
    1/3 (only the lower scorer counts as "scored less").
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 1, "drop_week": 18}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in range(1, 9)]
        + [_box_score(200, 2, w, 5) for w in range(1, 9)]
        + [_box_score(300, 3, w, 15) for w in range(1, 9)]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Waiver Wonder"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=8)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["total_points"] == 80
    assert row["num_weeks"] == 8
    assert row["waiver_score"] == round(100 / 3, 1)
    assert row["weeks"] == list(range(1, 9))
    # comparison field over weeks 1-8: player 100 (10s), 200 (5s), 300 (15s)
    # -> mean of all 24 datapoints = (80 + 40 + 120) / 24 = 10.0
    assert row["position_ppg"] == 10.0


def test_compute_stint_scores_excludes_stints_under_min_weeks():
    """A stint below min_weeks qualifying weeks must be excluded entirely."""
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 1, "drop_week": 6}]
    )
    box_scores = pd.DataFrame([_box_score(100, 1, w, 10) for w in range(1, 6)])
    players = pd.DataFrame([{"player_id": 100, "player_name": "Short Stint"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=8)

    assert result.empty


def test_compute_stint_scores_min_weeks_one_includes_single_week_stint():
    """
    A relaxed min_weeks=1 must let a single qualifying week score, unlike
    the default waiver-only min_weeks=8 — this is what makes the engine
    usable for "was this one acquisition a good move" questions, not just
    ranking a large field of established pickups.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 5, "drop_week": 6}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, 5, 20)]
        + [_box_score(200, 2, 5, 10)]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "One Week Wonder"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=1)

    assert len(result) == 1
    assert result.iloc[0]["num_weeks"] == 1
    assert result.iloc[0]["total_points"] == 20


def test_compute_stint_scores_only_uses_weeks_on_roster():
    """
    Box scores outside [acquisition_week, drop_week) — e.g. before the
    player was added — must not leak into the stint's top-N selection.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 5, "drop_week": 18}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 100) for w in range(1, 5)]  # before acquisition — must be ignored
        + [_box_score(100, 1, w, 10) for w in range(5, 13)]  # 8 weeks on roster
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Late Add"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=8)

    assert result.iloc[0]["total_points"] == 80  # 8 weeks x 10, not inflated by the pre-add 100s


def test_compute_stint_scores_ignores_zero_duration_stints():
    """
    A stint with acquisition_week == drop_week (duration 0 — a same-week
    add/drop or a drafted-and-immediately-cut player) had zero real weeks
    on the roster. Even with min_weeks=1 it must be excluded entirely, not
    scored as a 0-week stint or allowed to leak box scores into another
    team's later stint for the same player.
    """
    stints = pd.DataFrame(
        [
            {"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 1, "drop_week": 1},
            {"player_id": 100, "team_id": 2, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 2, "drop_week": 3},
        ]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, 1, 999)]  # zero-duration stint's box score — must not leak in
        + [_box_score(100, 2, 2, 20)]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Cut Same Week"}])
    teams = pd.DataFrame(
        [
            {"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"},
            {"team_id": 2, "season": 2024, "team_name": "Team B", "owner_name": "Bob"},
        ]
    )

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=1)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["team_name"] == "Team B"
    assert row["total_points"] == 20


def test_compute_stint_scores_merges_same_manager_discontinuous_stints():
    """
    A manager who waiver-added, dropped, and re-added the same player gets
    ONE scored entry, pooling their best weeks across both stints — this
    is what makes the score answer "how good was this manager at getting
    value from this player," not "how good was this one claim." Before
    this merge, two separate percentile rows for the same player/manager
    would visually stack into a single bar exceeding 100 on the Best
    Waiver chart (2024: Jameson Williams).
    """
    stints = pd.DataFrame(
        [
            {"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 1, "drop_week": 5},
            {"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 8, "drop_week": 12},
        ]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in range(1, 5)]  # first stint: 4 weeks
        + [_box_score(100, 1, w, 10) for w in range(8, 12)]  # second stint: 4 weeks
        + [_box_score(200, 2, w, 5) for w in list(range(1, 5)) + list(range(8, 12))]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Re-Added Player"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=8)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["num_weeks"] == 8  # pooled across both stints, meets min_weeks=8
    assert row["total_points"] == 80
    assert row["acquisition_week"] == 1  # first time this manager added the player
    assert 0 <= row["waiver_score"] <= 100


def test_compute_stint_scores_weeks_are_chronological_not_rank_order():
    """
    weeks must be sorted chronologically for display, not left in the
    points-descending rank order used internally to pick the top N —
    e.g. a player's best-scoring week can come late in the stint, but
    the reported week list should still read low-to-high.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 1, "drop_week": 5}]
    )
    # points-descending rank order is week 4 (40), week 1 (30), week 3 (20) —
    # deliberately not chronological, to prove the output re-sorts it
    box_scores = pd.DataFrame(
        [
            _box_score(100, 1, 1, 30),
            _box_score(100, 1, 2, 5),
            _box_score(100, 1, 3, 20),
            _box_score(100, 1, 4, 40),
        ]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Late Bloomer"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=3, min_weeks=1)

    assert result.iloc[0]["weeks"] == [1, 3, 4]


def test_compute_stint_scores_does_not_merge_different_managers():
    """
    Two different managers each picking up the same player in the same
    season must stay separate entries — merging is per-manager, not
    per-player. Otherwise two unrelated managers' percentile scores could
    stack into one over-100 bar in the chart.
    """
    stints = pd.DataFrame(
        [
            {"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 1, "drop_week": 9},
            {"player_id": 100, "team_id": 2, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 9, "drop_week": 18},
        ]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in range(1, 9)]
        + [_box_score(100, 2, w, 10) for w in range(9, 18)]
        + [_box_score(200, 3, w, 5) for w in range(1, 18)]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Two Managers"}])
    teams = pd.DataFrame(
        [
            {"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"},
            {"team_id": 2, "season": 2024, "team_name": "Team B", "owner_name": "Bob"},
        ]
    )

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=8)

    assert len(result) == 2
    assert set(result["owner_name"]) == {"Alice", "Bob"}
    assert (result["waiver_score"] <= 100).all()


def test_compute_stint_scores_does_not_merge_different_acquisition_types():
    """
    A manager who drafted a player, then later re-added him off waivers,
    must get two separate entries — one judging the draft pick, one
    judging the waiver pickup. Merging across acquisition types would
    make roster_value's "was this specific move good" answer meaningless.
    """
    stints = pd.DataFrame(
        [
            {"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "DRAFT",
             "acquisition_week": 1, "drop_week": 3},
            {"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 10, "drop_week": 18},
        ]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in range(1, 3)]
        + [_box_score(100, 1, w, 10) for w in range(10, 18)]
        + [_box_score(200, 2, w, 5) for w in list(range(1, 3)) + list(range(10, 18))]
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Drafted Then Rewaivered"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=1)

    assert len(result) == 2
    assert set(result["acquisition_type"]) == {"DRAFT", "WAIVER"}
