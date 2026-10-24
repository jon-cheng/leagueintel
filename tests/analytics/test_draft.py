# tests/analytics/test_draft.py
import pandas as pd
from leagueintel.analytics.draft import compute_draft_roi


def test_compute_draft_roi_excludes_ir():
    """
    Regression test: a player on IR every week should not count
    as 'started' even though IR is not the bench slot.

    This bug was caught when Christian McCaffrey who was injured all 2024,
    showed up incorrectly with a high number of starts and low points-per-game because IR
    weeks were counted as starts.
    """
    df = pd.DataFrame(
        [
            {
                "player_name": "Injured Player",
                "bid_amount": 50,
                "owner_name": "Test",
                "position": "RB",
                "lineup_slot": "IR",
                "points": 0.0,
                "week": w,
            }
            for w in range(1, 18)
        ]
    )
    result = compute_draft_roi(df)
    assert "Injured Player" not in result["player_name"].values


def test_compute_draft_roi_min_weeks_zero_includes_low_start_players():
    """
    The Draft Selections table shows every drafted player, unlike the ROI
    plot which cuts off below MIN_WEEKS starts — min_weeks=0 must let a
    player with a single start through instead of being filtered out.
    """
    df = pd.DataFrame(
        [
            {
                "player_name": "Bench Warmer",
                "bid_amount": 5,
                "owner_name": "Test",
                "position": "WR",
                "lineup_slot": "WR",
                "points": 8.0,
                "week": 1,
            }
        ]
    )
    result = compute_draft_roi(df, min_weeks=0)
    assert "Bench Warmer" in result["player_name"].values


def test_compute_draft_roi_unplayed_start_is_not_a_game():
    """
    Protects against an unplayed week counting as a game started. A
    player slotted into this week's lineup whose game hasn't happened has
    NULL points (NaN); counting that row as a start used to drag his
    points-per-game down as if he'd scored 0.
    """
    df = pd.DataFrame(
        [
            {"player_name": "Starter", "bid_amount": 30, "owner_name": "Test",
             "position": "WR", "lineup_slot": "WR", "points": pts, "week": w}
            for w, pts in [(1, 10.0), (2, 20.0), (3, None)]  # week 3 not played yet
        ]
    )
    row = compute_draft_roi(df, min_weeks=0).iloc[0]
    assert row["games_started"] == 2
    assert row["points_per_game"] == 15.0
