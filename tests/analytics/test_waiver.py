# tests/analytics/test_waiver.py
import pandas as pd
from leagueintel.analytics.waiver import compute_waiver_scores, compute_acquisition_history


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
        [{"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
          "acquisition_week": 1, "drop_week": 6}]
    )
    box_scores = pd.DataFrame([_box_score(100, 1, w, 10) for w in range(1, 6)])
    players = pd.DataFrame([{"player_id": 100, "player_name": "Short Stint"}])
    teams = pd.DataFrame([{"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"}])

    result = compute_waiver_scores(stints, box_scores, players, teams)

    assert result.empty
    assert list(result.columns) == [
        "player_name", "team_name", "owner_name", "position",
        "acquisition_week", "num_weeks", "total_points",
        "weeks", "median_total_points", "waiver_score",
    ]


def test_compute_waiver_scores_only_uses_weeks_on_roster():
    """
    Box scores outside [acquisition_week, drop_week) — e.g. before the
    player was added — must not leak into the stint's top-8 selection.
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

    result = compute_waiver_scores(stints, box_scores, players, teams)

    assert result.iloc[0]["total_points"] == 80  # 8 weeks x 10, not inflated by the pre-add 100s


def test_compute_waiver_scores_ignores_same_week_add_drop_stints():
    """
    A stint with acquisition_week == drop_week (duration_weeks == 0) is a
    same-week add/drop — a real "regrettable drop" row in waiver_stints,
    but zero actual weeks on the roster. It must be excluded entirely from
    waiver value scoring, not scored as a 0-week stint or allowed to leak
    box scores into another team's later stint for the same player.
    """
    stints = pd.DataFrame(
        [
            {"player_id": 100, "team_id": 1, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 6, "drop_week": 6},
            {"player_id": 100, "team_id": 2, "season": 2024, "acquisition_type": "WAIVER",
             "acquisition_week": 7, "drop_week": 15},
        ]
    )
    box_scores = pd.DataFrame(
        [_box_score(100, 1, 6, 999)]  # same-week stint's box score — must not leak in
        + [_box_score(100, 2, w, 10) for w in range(7, 15)]  # 8 weeks on the real stint
    )
    players = pd.DataFrame([{"player_id": 100, "player_name": "Cut Same Week"}])
    teams = pd.DataFrame(
        [
            {"team_id": 1, "season": 2024, "team_name": "Team A", "owner_name": "Alice"},
            {"team_id": 2, "season": 2024, "team_name": "Team B", "owner_name": "Bob"},
        ]
    )

    result = compute_waiver_scores(stints, box_scores, players, teams)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["team_name"] == "Team B"
    assert row["total_points"] == 80  # 8 weeks x 10, not the 999 from the same-week stint


def _team(team_id, owner_name, season=2024):
    return {"team_id": team_id, "season": season, "team_name": f"Team {team_id}", "owner_name": owner_name}


def _stint(player_id, team_id, acquisition_type, acquisition_week, drop_week, season=2024):
    return {
        "player_id": player_id,
        "team_id": team_id,
        "season": season,
        "acquisition_type": acquisition_type,
        "acquisition_week": acquisition_week,
        "drop_week": drop_week,
    }


def _bid(player_id, team_id, transaction_type, week, bid_amount):
    return {
        "player_id": player_id,
        "team_id": team_id,
        "transaction_type": transaction_type,
        "week": week,
        "bid_amount": bid_amount,
    }


def test_compute_acquisition_history_lists_every_manager_chronologically():
    """
    A player claimed by multiple managers over the season must show every
    stint, in week order — not just the most recent one — since the
    whole point is showing how a player churned through the league, not
    just who currently owns them. Prices attach only to the matching
    acquisition (waiver bid vs waiver bid), never crossing between stints.
    """
    stints = pd.DataFrame(
        [
            _stint(100, 1, "WAIVER", 3, 7),
            _stint(100, 2, "WAIVER", 10, 18),
        ]
    )
    bids = pd.DataFrame(
        [
            _bid(100, 1, "WAIVER", 3, 8),
            _bid(100, 2, "WAIVER", 10, 7),
        ]
    )
    teams = pd.DataFrame([_team(1, "Daniel Corbett"), _team(2, "Calvin Cotton")])

    result = compute_acquisition_history(stints, bids, teams)

    assert len(result) == 1
    assert result.iloc[0]["player_id"] == 100
    assert result.iloc[0]["history"] == (
        "Daniel Corbett: (Waiver, $8, Wk 3-6); Calvin Cotton: (Waiver, $7, Wk 10-17)"
    )


def test_compute_acquisition_history_trade_has_no_price():
    """TRADE (and FREEAGENT) stints have no matching row in bids, so no price should be shown."""
    stints = pd.DataFrame([_stint(200, 3, "TRADE", 7, 18)])
    bids = pd.DataFrame(columns=["player_id", "team_id", "transaction_type", "week", "bid_amount"])
    teams = pd.DataFrame([_team(3, "Chris Everson")])

    result = compute_acquisition_history(stints, bids, teams)

    assert result.iloc[0]["history"] == "Chris Everson: (Trade, Wk 7-17)"


def test_compute_acquisition_history_draft_has_auction_price():
    """DRAFT stints price from the DRAFT transaction's bid_amount, not a waiver bid."""
    stints = pd.DataFrame([_stint(300, 1, "DRAFT", 1, 18)])
    bids = pd.DataFrame([_bid(300, 1, "DRAFT", 1, 55)])
    teams = pd.DataFrame([_team(1, "Daniel Corbett")])

    result = compute_acquisition_history(stints, bids, teams)

    assert result.iloc[0]["history"] == "Daniel Corbett: (Draft, $55, Wk 1-17)"


def test_compute_acquisition_history_same_week_add_drop_shows_single_week():
    """A same-week add/cut (duration_weeks == 0) has no real second week — show it as one week, not a backwards range."""
    stints = pd.DataFrame([_stint(400, 1, "WAIVER", 6, 6)])
    bids = pd.DataFrame([_bid(400, 1, "WAIVER", 6, 1)])
    teams = pd.DataFrame([_team(1, "Daniel Corbett")])

    result = compute_acquisition_history(stints, bids, teams)

    assert result.iloc[0]["history"] == "Daniel Corbett: (Waiver, $1, Wk 6)"


def test_compute_acquisition_history_empty_input_returns_empty_frame():
    """An empty stints frame (e.g. a season with no roster activity yet) must not error."""
    stints = pd.DataFrame(columns=["player_id", "team_id", "acquisition_type", "acquisition_week", "drop_week"])
    bids = pd.DataFrame(columns=["player_id", "team_id", "transaction_type", "week", "bid_amount"])
    teams = pd.DataFrame(columns=["team_id", "season", "team_name", "owner_name"])

    result = compute_acquisition_history(stints, bids, teams)

    assert result.empty
    assert list(result.columns) == ["player_id", "history"]
