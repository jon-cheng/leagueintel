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
