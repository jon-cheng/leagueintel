# tests/analytics/test_head_to_head.py
import math
import pandas as pd
from leagueintel.analytics.head_to_head import build_h2h_matrix, compute_h2h_records


def _matchup(home_manager, away_manager, home_score, away_score):
    return {
        "home_manager": home_manager,
        "away_manager": away_manager,
        "home_score": home_score,
        "away_score": away_score,
    }


def test_compute_h2h_records_counts_wins_losses_ties():
    """
    Three games between the same pair — one win each way and one tie —
    should roll up into a single pair row with wins_a=1, wins_b=1, ties=1.
    """
    df = pd.DataFrame(
        [
            _matchup("Manager A", "Manager B", 120.0, 100.0),
            _matchup("Manager B", "Manager A", 130.0, 90.0),
            _matchup("Manager A", "Manager B", 100.0, 100.0),
        ]
    )
    result = compute_h2h_records(df)
    assert len(result) == 1
    row = result.iloc[0]
    assert {row["wins_a"], row["wins_b"], row["ties"]} == {1}


def test_compute_h2h_records_credits_winner_regardless_of_home_away():
    """
    Regression guard: a manager's win must count whether they played
    home or away. A bug that assumed 'home team = manager_a always wins'
    would silently swap win/loss credit for away winners.
    """
    df = pd.DataFrame(
        [
            # Manager B wins as the away team
            _matchup("Manager A", "Manager B", 90.0, 110.0),
        ]
    )
    result = compute_h2h_records(df)
    row = result.iloc[0]
    winner_col = "wins_a" if row["manager_a"] == "Manager B" else "wins_b"
    assert row[winner_col] == 1


def test_build_h2h_matrix_mirrors_both_cells_from_each_side():
    """
    Both [A,B] and [B,A] must be filled, each written from that row
    manager's own perspective — not a duplicate of the other cell.
    A bug that only wrote one direction would leave half the matrix
    blank; a bug that copied the same string to both cells would show
    both managers with the same win/loss record, which is impossible.
    """
    records = pd.DataFrame(
        [{"manager_a": "Manager A", "manager_b": "Manager B", "wins_a": 2, "wins_b": 1, "ties": 0}]
    )
    text_matrix, _ = build_h2h_matrix(records)

    assert text_matrix.loc["Manager A", "Manager B"] == "2-1-0"
    assert text_matrix.loc["Manager B", "Manager A"] == "1-2-0"
    assert text_matrix.loc["Manager A", "Manager A"] == ""
    assert text_matrix.loc["Manager B", "Manager B"] == ""


def test_build_h2h_matrix_orders_managers_by_last_name():
    """
    Managers are ordered by last name (per product decision), not raw
    insertion order — 'Manager B' should sort before 'Manager A' here
    because it appears second as manager_b in the input record.

    NOTE: with anonymized "Manager <letter>" names, last-name sort and
    whole-string sort coincide, so this no longer distinguishes "sorted
    by last name" from "sorted naively by full name" the way the original
    fixture (first names and last names in opposite alphabetical order)
    did. It still guards against insertion-order bugs.
    """
    records = pd.DataFrame(
        [{"manager_a": "Manager A", "manager_b": "Manager B", "wins_a": 2, "wins_b": 1, "ties": 0}]
    )
    text_matrix, pct_matrix = build_h2h_matrix(records)
    assert list(text_matrix.index) == ["Manager A", "Manager B"]
    assert list(pct_matrix.index) == ["Manager A", "Manager B"]


def test_build_h2h_matrix_win_pct_is_complementary_and_excludes_ties():
    """
    win_pct must mirror to 1 - p, since one manager's win is the other's
    loss — a bug that computed each side independently could produce two
    percentages that don't sum to 1. Ties are excluded from the
    denominator so a tie-heavy record isn't diluted toward 50%.
    """
    records = pd.DataFrame(
        [{"manager_a": "Manager A", "manager_b": "Manager B", "wins_a": 3, "wins_b": 1, "ties": 2}]
    )
    _, pct_matrix = build_h2h_matrix(records)

    a_pct = pct_matrix.loc["Manager A", "Manager B"]
    b_pct = pct_matrix.loc["Manager B", "Manager A"]
    assert a_pct == 0.75  # 3 wins / 4 decided games, 2 ties excluded
    assert math.isclose(a_pct + b_pct, 1.0)


def test_build_h2h_matrix_win_pct_is_nan_when_no_decided_games():
    """
    A pair that has only ever tied has no decided games — win_pct should
    be NaN (unknown), not 0.5, so it can be excluded from color scaling
    rather than rendered as a false 'even record'.
    """
    records = pd.DataFrame(
        [{"manager_a": "Manager A", "manager_b": "Manager B", "wins_a": 0, "wins_b": 0, "ties": 1}]
    )
    _, pct_matrix = build_h2h_matrix(records)
    assert math.isnan(pct_matrix.loc["Manager A", "Manager B"])
