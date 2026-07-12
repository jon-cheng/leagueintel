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
