# tests/analytics/test_war.py
import numpy as np
import pandas as pd
import pytest
from leagueintel.analytics.war import (
    fit_win_probability_model,
    win_probability,
    _replacement_levels,
    compute_season_war,
)


# ── fit_win_probability_model / win_probability ─────────────────────────────


def test_win_probability_is_fifty_fifty_at_zero_margin():
    assert win_probability(0.0, coef=1.5, intercept=0.0) == pytest.approx(0.5)


def test_fit_win_probability_model_learns_positive_coef_from_separated_data():
    """
    A team that outscores its opponent should end up predicted more
    likely to win — coef must come out positive on a dataset where
    margin and win are clearly correlated, not just close to zero from
    an undertrained fit.
    """
    rng = np.random.default_rng(0)
    margins = rng.normal(0, 20, size=200)
    wins = (margins > 0).astype(float)
    team_games = pd.DataFrame({"margin": margins, "win": wins})

    coef, intercept = fit_win_probability_model(team_games)

    assert coef > 0
    # a decisive win margin should predict a decisive win probability
    assert win_probability(40, coef, intercept) > 0.9
    assert win_probability(-40, coef, intercept) < 0.1


# ── _replacement_levels ──────────────────────────────────────────────────────


def test_replacement_level_is_bench_average_not_worst_starter():
    """
    Two teams, RB, week 1: two starters (18, 12 pts) and one bench RB
    (15 pts) who didn't start anywhere. Replacement level should be the
    bench pool's average (15, with only one bench player) — not 12 (the
    worst actual starter), which would floor every starter's WAR at >= 0.
    """
    box_scores = pd.DataFrame(
        [
            {"position": "RB", "week": 1, "lineup_slot": "RB", "points": 18.0},
            {"position": "RB", "week": 1, "lineup_slot": "RB", "points": 12.0},
            {"position": "RB", "week": 1, "lineup_slot": "BE", "points": 15.0},
        ]
    )
    replacement = _replacement_levels(box_scores)
    assert replacement[("RB", 1)] == 15.0


def test_replacement_level_averages_the_whole_bench_pool():
    """
    Real-data check that motivated this design: a single stud parked on
    a bench (e.g. a bye-week or depth-chart casualty) must not single-
    handedly set replacement level to a near-elite score. Two bench RBs
    (30 and 6 pts) should average to 18, not spike to the max of 30.
    """
    box_scores = pd.DataFrame(
        [
            {"position": "RB", "week": 1, "lineup_slot": "RB", "points": 10.0},
            {"position": "RB", "week": 1, "lineup_slot": "BE", "points": 30.0},
            {"position": "RB", "week": 1, "lineup_slot": "BE", "points": 6.0},
        ]
    )
    replacement = _replacement_levels(box_scores)
    assert replacement[("RB", 1)] == 18.0


# ── compute_season_war ───────────────────────────────────────────────────────


def _team_games_fixture():
    # team 1 beats team 2, 120-100, in week 1 — only game that season
    return pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "team_id": 1,
                "opp_team_id": 2,
                "team_score": 120.0,
                "opp_score": 100.0,
            },
            {
                "season": 2025,
                "week": 1,
                "team_id": 2,
                "opp_team_id": 1,
                "team_score": 100.0,
                "opp_score": 120.0,
            },
        ]
    )


def test_ir_player_gets_zero_war_never_negative_or_positive():
    """
    Regression guard mirroring test_compute_draft_roi_excludes_ir: an IR
    slot must never be treated as a start, or a hurt player who banked
    zero points would look like a below-replacement disaster.
    """
    box_scores = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "team_id": 1,
                "player_id": 1,
                "player_name": "Injured Player",
                "position": "RB",
                "lineup_slot": "IR",
                "points": 0.0,
            },
            {
                "season": 2025,
                "week": 1,
                "team_id": 1,
                "player_id": 2,
                "player_name": "Bench RB",
                "position": "RB",
                "lineup_slot": "BE",
                "points": 10.0,
            },
        ]
    )
    result = compute_season_war(box_scores, _team_games_fixture(), coef=0.05, intercept=0.0)
    assert "Injured Player" not in result["player_name"].values


def test_started_player_who_beat_replacement_gets_positive_war():
    box_scores = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "team_id": 1,
                "player_id": 1,
                "player_name": "Team1 Starter",
                "position": "RB",
                "lineup_slot": "RB",
                "points": 25.0,
            },
            {
                "season": 2025,
                "week": 1,
                "team_id": 2,
                "player_id": 2,
                "player_name": "Team2 Bench",
                "position": "RB",
                "lineup_slot": "BE",
                "points": 8.0,  # the replacement-level alternative
            },
        ]
    )
    result = compute_season_war(box_scores, _team_games_fixture(), coef=0.05, intercept=0.0)
    starter_row = result[result["player_name"] == "Team1 Starter"].iloc[0]
    assert starter_row["season_war"] > 0
