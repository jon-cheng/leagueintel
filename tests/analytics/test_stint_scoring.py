# tests/analytics/test_stint_scoring.py
import pandas as pd
from leagueintel.analytics.stint_scoring import compute_stint_scores, compute_stint_scores_with_population


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
    # median_total_points = median of comparison TOTALS (80, 40, 120),
    # sorted [40, 80, 120] -> median = 80.0
    assert row["median_total_points"] == 80.0


def test_compute_stint_scores_median_total_points_is_median_not_mean():
    """
    median_total_points must use the MEDIAN of the comparison field's
    totals, not the mean -- position scoring is right-skewed (a few
    high-scoring starters, many near-zero bench/committee players), so a
    mean gets pulled up by outliers and misrepresents what "typical"
    looked like.

    Field: 9 low-scoring comparison players (5 pts/week) + 1 outlier
    (100 pts/week), over 2 weeks -- so totals are 10 (x9) and 200 (x1).
    Mean of totals would be ~28; median is 10 -- deliberately far apart
    so a regression back to mean fails loudly.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 1, "drop_week": 3}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in (1, 2)]
        + [_box_score(200 + i, 2 + i, w, 5) for i in range(9) for w in (1, 2)]
        + [_box_score(300, 11, w, 100) for w in (1, 2)]
    )
    players = pd.DataFrame(
        [{"player_id": 100, "player_name": "Waiver Wonder"}]
        + [{"player_id": 200 + i, "player_name": f"Low Scorer {i}"} for i in range(9)]
        + [{"player_id": 300, "player_name": "Outlier"}]
    )
    teams = pd.DataFrame(
        [{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}]
        + [{"team_id": 2 + i, "season": 2024, "team_name": f"Team {i}", "owner_name": f"Owner {i}"} for i in range(9)]
        + [{"team_id": 11, "season": 2024, "team_name": "Team K", "owner_name": "Kyle"}]
    )

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=2, min_weeks=2)

    assert result.iloc[0]["median_total_points"] == 10.0


def test_compute_stint_scores_median_total_points_uses_totals_not_per_week_values():
    """
    median_total_points must be derived from the median of comparison
    players' TOTALS (each player collapsed to one number), not the
    median of every individual player-week point value -- these diverge
    whenever comparison players were rostered unequal numbers of weeks,
    since a per-week-value median implicitly weights players by how many
    weeks they contributed rows for, while a median of totals weights
    every player equally (matching how waiver_score itself compares
    whole totals, not per-week values).

    Query: total 80 over 8 weeks. Comparison: A (40 over 8 weeks), B (50
    over just 1 week), C (120 over 8 weeks).
      - a per-week-value median (25 individual point values: eight 10s,
        eight 5s, one 50, eight 15s) would give 10.0
      - median of totals [40, 50, 80, 120] gives (50 + 80) / 2 = 65.0
    These numbers are deliberately different so a regression back to a
    per-week-value computation fails loudly.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 1, "drop_week": 9}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in range(1, 9)]  # query: 80 over 8 weeks
        + [_box_score(200, 2, w, 5) for w in range(1, 9)]  # A: 40 over 8 weeks
        + [_box_score(300, 3, 1, 50)]  # B: 50 over just 1 week
        + [_box_score(400, 4, w, 15) for w in range(1, 9)]  # C: 120 over 8 weeks
    )
    players = pd.DataFrame(
        [
            {"player_id": 100, "player_name": "Waiver Wonder"},
            {"player_id": 200, "player_name": "Full Window A"},
            {"player_id": 300, "player_name": "One Week B"},
            {"player_id": 400, "player_name": "Full Window C"},
        ]
    )
    teams = pd.DataFrame(
        [
            {"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"},
            {"team_id": 2, "season": 2024, "team_name": "Team B", "owner_name": "Bob"},
            {"team_id": 3, "season": 2024, "team_name": "Team C", "owner_name": "Carol"},
            {"team_id": 4, "season": 2024, "team_name": "Team D", "owner_name": "Dana"},
        ]
    )

    result = compute_stint_scores(stints, box_scores, players, teams, top_n_weeks=8, min_weeks=8)

    assert result.iloc[0]["median_total_points"] == 65.0


def test_compute_stint_scores_with_population_exposes_comparison_field():
    """
    compute_stint_scores_with_population must expose the individual
    comparison players behind a score, not just the aggregated
    median_total_points/waiver_score — this is what a transparency
    drilldown (e.g. a beeswarm of the comparison field) needs to render.
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
    players = pd.DataFrame(
        [
            {"player_id": 100, "player_name": "Waiver Wonder"},
            {"player_id": 200, "player_name": "Low Scorer"},
            {"player_id": 300, "player_name": "High Scorer"},
        ]
    )
    teams = pd.DataFrame(
        [
            {"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"},
            {"team_id": 2, "season": 2024, "team_name": "Team B", "owner_name": "Bob"},
            {"team_id": 3, "season": 2024, "team_name": "Team C", "owner_name": "Carol"},
        ]
    )

    result, population = compute_stint_scores_with_population(
        stints, box_scores, players, teams, top_n_weeks=8, min_weeks=8
    )

    assert len(result) == 1
    # 3 comparison players (100, 200, 300) over the query player's 8 qualifying weeks
    assert len(population) == 3
    assert set(population["comparison_player_name"]) == {"Waiver Wonder", "Low Scorer", "High Scorer"}

    totals_by_name = dict(zip(population["comparison_player_name"], population["comparison_total"]))
    assert totals_by_name == {"Waiver Wonder": 80, "Low Scorer": 40, "High Scorer": 120}

    # all three rostered every one of the 8 qualifying weeks here, so ppg == total / 8
    ppg_by_name = dict(zip(population["comparison_player_name"], population["comparison_ppg"]))
    assert ppg_by_name == {"Waiver Wonder": 10.0, "Low Scorer": 5.0, "High Scorer": 15.0}

    query_row = population[population["is_query_player"]]
    assert len(query_row) == 1
    assert query_row.iloc[0]["comparison_player_name"] == "Waiver Wonder"
    assert query_row.iloc[0]["query_total_points"] == 80

    # comparison_owner_name is the comparison player's manager, for hover
    # display — not to be confused with the query player's own manager
    owner_by_name = dict(zip(population["comparison_player_name"], population["comparison_owner_name"]))
    assert owner_by_name == {"Waiver Wonder": "Alice", "Low Scorer": "Bob", "High Scorer": "Carol"}

    # weeks is the query's own qualifying weeks, carried onto every row
    # for display alongside each comparison player's stat line
    assert all(population["weeks"].apply(lambda ws: ws == list(range(1, 9))))


def test_compute_stint_scores_with_population_ppg_uses_games_actually_played():
    """
    comparison_ppg must divide by the weeks a comparison player was
    ACTUALLY rostered within the query's qualifying window, not by the
    query player's own num_weeks -- a comparison player only rostered for
    part of that window (e.g. added mid-way) would otherwise get an
    artificially deflated PPG.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 1, "drop_week": 5}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in range(1, 5)]  # query: 4 weeks, 40 total
        + [_box_score(200, 2, 3, 30)]  # comparison player only rostered 1 of those 4 weeks
    )
    players = pd.DataFrame(
        [
            {"player_id": 100, "player_name": "Waiver Wonder"},
            {"player_id": 200, "player_name": "Late Arrival"},
        ]
    )
    teams = pd.DataFrame(
        [
            {"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"},
            {"team_id": 2, "season": 2024, "team_name": "Team B", "owner_name": "Bob"},
        ]
    )

    _result, population = compute_stint_scores_with_population(
        stints, box_scores, players, teams, top_n_weeks=4, min_weeks=4
    )

    late_arrival = population[population["comparison_player_name"] == "Late Arrival"].iloc[0]
    assert late_arrival["comparison_total"] == 30
    # 30 over 1 game played = 30.0, NOT 30 / 4 (the query's num_weeks) = 7.5
    assert late_arrival["comparison_ppg"] == 30.0


def test_compute_stint_scores_with_population_combines_traded_comparison_player():
    """
    A comparison player traded mid-window (rostered by team 2 for the
    first half of the query's qualifying weeks, team 4 for the second)
    must still count as ONE combined total for scoring — splitting them
    into two smaller per-team partial totals would make each partial more
    likely to register as "scored less" than the query's full total,
    silently inflating waiver_score. This is a regression test for
    exactly that bug, introduced and caught while adding team_id to the
    population frame for display.
    """
    stints = pd.DataFrame(
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 1, "drop_week": 18}]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, w, 10) for w in range(1, 9)]  # query player: 80 total
        + [_box_score(200, 2, w, 6) for w in range(1, 5)]  # traded comparison player,
        + [_box_score(200, 4, w, 6) for w in range(5, 9)]  # first half team 2, second half team 4 -> 48 total
    )
    players = pd.DataFrame(
        [
            {"player_id": 100, "player_name": "Waiver Wonder"},
            {"player_id": 200, "player_name": "Traded Player"},
        ]
    )
    teams = pd.DataFrame(
        [
            {"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"},
            {"team_id": 2, "season": 2024, "team_name": "Team B", "owner_name": "Bob"},
            {"team_id": 4, "season": 2024, "team_name": "Team D", "owner_name": "Dana"},
        ]
    )

    result, population = compute_stint_scores_with_population(
        stints, box_scores, players, teams, top_n_weeks=8, min_weeks=8
    )

    # combined (48) < query's 80 -> counts as exactly one "scored less" out
    # of 2 comparison entries (traded player + query player themselves) = 50%.
    # If split into two 24-point halves, that would still be 2 of 3 entries
    # scoring less (67%) -- a different, wrong number, which is the bug
    # this test guards against.
    assert result.iloc[0]["waiver_score"] == 50.0

    traded_player_rows = population[population["comparison_player_name"] == "Traded Player"]
    assert len(traded_player_rows) == 1  # one combined row, not split by team
    assert traded_player_rows.iloc[0]["comparison_total"] == 48
    assert traded_player_rows.iloc[0]["comparison_team_name"] == "Team D"  # last team


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
