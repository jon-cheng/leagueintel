# tests/integration/test_daily_refresh.py
"""
Integration test for the daily sync pipeline.

Runs the full fetch -> write -> SQLite flow twice against a real (tmp file)
database, simulating two consecutive daily cron runs within the same NFL
week. ESPN's mocked responses change between "day 1" and "day 2" the way
real in-season data would: box score points rise, a matchup score updates,
and a transaction moves from PENDING to EXECUTED. Unit tests already cover
each writer function in isolation — this proves the whole pipeline behaves
correctly together, end to end, the way the actual cron exercises it.
"""

import sqlite3
from unittest.mock import patch, MagicMock

from leagueintel.ingestion.espn import (
    fetch_teams_all,
    fetch_players_all,
    fetch_box_scores_all,
    fetch_matchups_all,
    fetch_transactions_all,
)
from leagueintel.ingestion.parse import parse_transactions_all


def _fake_team(team_id: int, name: str) -> MagicMock:
    team = MagicMock()
    team.team_id = team_id
    team.team_name = name
    team.team_abbrev = name[:3].upper()
    team.owners = [{"firstName": "Test", "lastName": f"Owner{team_id}"}]
    return team


def _fake_player(player_id: int, points: float) -> MagicMock:
    player = MagicMock()
    player.playerId = player_id
    player.name = f"Player{player_id}"
    player.position = "RB"
    player.lineupSlot = "RB"
    player.proTeam = "SF"
    player.points = points
    player.projected_points = 10.0
    player.on_bye_week = False
    player.game_played = 100
    return player


def _fake_matchup(
    home_team,
    away_team,
    home_score: float,
    away_score: float,
    home_player_points: float,
    away_player_points: float,
) -> MagicMock:
    matchup = MagicMock()
    matchup.home_team = home_team
    matchup.away_team = away_team
    matchup.home_score = home_score
    matchup.away_score = away_score
    matchup.home_projected = home_score + 5
    matchup.away_projected = away_score + 5
    matchup.is_playoff = False
    matchup.matchup_type = "NONE"
    matchup.home_lineup = [_fake_player(100, home_player_points)]
    matchup.away_lineup = [_fake_player(200, away_player_points)]
    return matchup


def _build_fake_league(
    final_scoring_period: int,
    home_score: float,
    away_score: float,
    home_player_points: float,
    away_player_points: float,
) -> MagicMock:
    team_a = _fake_team(1, "Team A")
    team_b = _fake_team(2, "Team B")

    league = MagicMock()
    league.finalScoringPeriod = final_scoring_period
    league.teams = [team_a, team_b]
    league.player_map = {100: "Player100", 200: "Player200"}
    league.box_scores.return_value = [
        _fake_matchup(
            team_a, team_b, home_score, away_score, home_player_points, away_player_points
        )
    ]
    return league


def _transaction_response(status: str, process_date) -> dict:
    return {
        "transactions": [
            {
                "id": "txn1",
                "type": "WAIVER",
                "status": status,
                "bidAmount": 25,
                "teamId": 1,
                "scoringPeriodId": 1,
                "executionType": "EXECUTE",
                "proposedDate": 1000,
                "processDate": process_date,
                "items": [
                    {"type": "ADD", "playerId": 100, "toTeamId": 1, "fromTeamId": 0}
                ],
            }
        ]
    }


def _run_daily_sync(fake_league, transactions_response, raw_dir):
    with patch("leagueintel.ingestion.espn.League", return_value=fake_league):
        with patch("leagueintel.ingestion.espn.time.sleep"):
            fetch_teams_all(seasons=[2026])
            fetch_players_all(seasons=[2026])
            fetch_box_scores_all(seasons=[2026])
            fetch_matchups_all(seasons=[2026])

            with patch(
                "leagueintel.ingestion.espn._fetch_week",
                return_value=transactions_response,
            ):
                fetch_transactions_all(year=2026, output_dir=str(raw_dir))

    parse_transactions_all(seasons=[2026], input_dir=str(raw_dir))


def test_two_day_sync_refreshes_data_without_duplication(tmp_path):
    db_path = tmp_path / "leagueintel.db"
    raw_dir = tmp_path / "raw"

    with patch("leagueintel.ingestion.espn.LEAGUE_ID", "123"):
        with patch("leagueintel.ingestion.espn.ESPN_S2", "abc"):
            with patch("leagueintel.ingestion.espn.SWID", "{xyz}"):
                with patch(
                    "leagueintel.ingestion.espn.get_connection",
                    lambda *a, **kw: sqlite3.connect(db_path),
                ):
                    with patch(
                        "leagueintel.ingestion.parse.get_connection",
                        lambda *a, **kw: sqlite3.connect(db_path),
                    ):
                        # Day 1: week 1 in progress, transaction still pending.
                        day1_league = _build_fake_league(
                            final_scoring_period=1,
                            home_score=50.0,
                            away_score=45.0,
                            home_player_points=5.0,
                            away_player_points=8.0,
                        )
                        _run_daily_sync(
                            day1_league,
                            _transaction_response(status="PENDING", process_date=None),
                            raw_dir,
                        )

                        # Day 2: same week, scores have risen as games finished,
                        # and the transaction has since been executed.
                        day2_league = _build_fake_league(
                            final_scoring_period=1,
                            home_score=110.0,
                            away_score=95.0,
                            home_player_points=12.5,
                            away_player_points=20.0,
                        )
                        _run_daily_sync(
                            day2_league,
                            _transaction_response(
                                status="EXECUTED", process_date=2000
                            ),
                            raw_dir,
                        )

    conn = sqlite3.connect(db_path)

    # Matchup score reflects day 2, and there's still only one row.
    matchups = conn.execute(
        "SELECT home_score, away_score FROM matchups WHERE season = 2026 AND week = 1"
    ).fetchall()
    assert matchups == [(110.0, 95.0)]

    # Box scores reflect day 2 points, one row per player/week — not two.
    box_scores = conn.execute(
        "SELECT player_id, points FROM box_scores "
        "WHERE season = 2026 AND week = 1 ORDER BY player_id"
    ).fetchall()
    assert box_scores == [(100, 12.5), (200, 20.0)]

    # Transaction status refreshed to EXECUTED, one row for the id.
    transactions = conn.execute(
        "SELECT status, process_date FROM transactions WHERE id = 'txn1'"
    ).fetchall()
    assert transactions == [("EXECUTED", 2000)]

    # Transaction moves not duplicated across the two parse runs.
    move_count = conn.execute(
        "SELECT COUNT(*) FROM transaction_moves WHERE transaction_id = 'txn1'"
    ).fetchone()[0]
    assert move_count == 1

    # Teams table has exactly the two teams, not duplicated across two runs.
    team_count = conn.execute(
        "SELECT COUNT(*) FROM teams WHERE season = 2026"
    ).fetchone()[0]
    assert team_count == 2

    conn.close()
