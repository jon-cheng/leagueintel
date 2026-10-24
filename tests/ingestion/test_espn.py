# tests/ingestion/test_espn.py
import pytest
import requests
import json
from unittest.mock import patch, MagicMock
from pathlib import Path
from leagueintel.ingestion.espn import (
    _fetch_week,
    _save_raw,
    _summarize,
    fetch_transactions_all,
    fetch_teams_all,
    fetch_matchups_all,
    fetch_box_scores_all,
    build_leagues,
    _extract_player_week,
    _extract_matchup,
)
from leagueintel.storage.writer import BoxScoreRecord, MatchupRecord


# sample API response fixture
@pytest.fixture
def sample_response():
    return {
        "transactions": [
            {
                "id": "abc123",
                "type": "WAIVER",
                "status": "EXECUTED",
                "bidAmount": 25,
                "teamId": 3,
                "scoringPeriodId": 1,
                "items": [
                    {"type": "ADD", "playerId": 12345, "toTeamId": 3, "fromTeamId": 0}
                ],
            },
            {
                "id": "def456",
                "type": "WAIVER",
                "status": "FAILED_PLAYERALREADYDROPPED",
                "bidAmount": 18,
                "teamId": 7,
                "scoringPeriodId": 1,
                "items": [
                    {"type": "ADD", "playerId": 12345, "toTeamId": 7, "fromTeamId": 0}
                ],
            },
            {
                "id": "ghi789",
                "type": "DRAFT",
                "status": "EXECUTED",
                "bidAmount": 45,
                "teamId": 5,
                "scoringPeriodId": 1,
                "items": [
                    {"type": "ADD", "playerId": 99999, "toTeamId": 5, "fromTeamId": 0}
                ],
            },
        ]
    }


# ── _summarize tests ──────────────────────────────────────────────────────────


def test_summarize_counts_correctly(sample_response):
    transactions = sample_response["transactions"]
    waiver_executed, waiver_failed, draft = _summarize(transactions)
    assert waiver_executed == 1
    assert waiver_failed == 1
    assert draft == 1


def test_summarize_empty_transactions():
    waiver_executed, waiver_failed, draft = _summarize([])
    assert waiver_executed == 0
    assert waiver_failed == 0
    assert draft == 0


# ── _fetch_week tests ─────────────────────────────────────────────────────────


def test_fetch_week_success(sample_response):
    with patch("leagueintel.ingestion.espn.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = sample_response
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = _fetch_week(year=2024, week=1)

        assert result == sample_response
        mock_get.assert_called_once()


def test_fetch_week_http_error():
    with patch("leagueintel.ingestion.espn.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            response=MagicMock(status_code=404)
        )
        mock_get.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            _fetch_week(year=2024, week=1)


def test_fetch_week_timeout():
    with patch("leagueintel.ingestion.espn.requests.get") as mock_get:
        mock_get.side_effect = requests.Timeout()

        with pytest.raises(requests.Timeout):
            _fetch_week(year=2024, week=1)


# ── _save_raw tests ───────────────────────────────────────────────────────────


def test_save_raw_creates_file(tmp_path, sample_response):
    path = _save_raw(sample_response, year=2024, week=1, output_dir=tmp_path)

    saved_file = Path(path)
    assert saved_file.exists()
    assert saved_file.name == "week01.json"
    assert saved_file.parent.name == "2024"

    content = json.loads(saved_file.read_text())
    assert content == sample_response


def test_save_raw_s3_raises_not_implemented(sample_response):
    with pytest.raises(NotImplementedError):
        _save_raw(sample_response, year=2024, week=1, output_dir="s3://my-bucket/raw")


# ── fetch_transactions_all tests ──────────────────────────────────────────────


def test_fetch_transactions_all_missing_credentials():
    with patch("leagueintel.ingestion.espn.LEAGUE_ID", None):
        with patch("leagueintel.ingestion.espn.ESPN_S2", None):
            with patch("leagueintel.ingestion.espn.SWID", None):
                # should log error and return without raising
                fetch_transactions_all(year=2024, week=1)


def test_fetch_transactions_all_bounds_weeks_to_final_scoring_period(
    sample_response, tmp_path
):
    """
    Simulates being mid-season: ESPN reports finalScoringPeriod = 3, so only
    3 weeks have occurred so far. fetch_transactions_all should stop there
    instead of requesting all the way up to max_week/DEFAULT_MAX_WEEK.
    """
    fake_league = MagicMock()
    fake_league.finalScoringPeriod = 3

    with patch("leagueintel.ingestion.espn.LEAGUE_ID", "123"):
        with patch("leagueintel.ingestion.espn.ESPN_S2", "abc"):
            with patch("leagueintel.ingestion.espn.SWID", "{xyz}"):
                with patch(
                    "leagueintel.ingestion.espn.League", return_value=fake_league
                ):
                    with patch(
                        "leagueintel.ingestion.espn._fetch_week"
                    ) as mock_fetch:
                        with patch("leagueintel.ingestion.espn.time.sleep"):
                            mock_fetch.return_value = sample_response

                            fetch_transactions_all(
                                year=2026, output_dir=str(tmp_path)
                            )

    weeks_fetched = [c.args[1] for c in mock_fetch.call_args_list]
    assert weeks_fetched == [1, 2, 3]


def test_fetch_transactions_all_saves_file(sample_response, tmp_path):
    with patch("leagueintel.ingestion.espn.LEAGUE_ID", "123"):
        with patch("leagueintel.ingestion.espn.ESPN_S2", "abc"):
            with patch("leagueintel.ingestion.espn.SWID", "{xyz}"):
                with patch("leagueintel.ingestion.espn._fetch_week") as mock_fetch:
                    mock_fetch.return_value = sample_response

                    fetch_transactions_all(year=2024, week=1, output_dir=str(tmp_path))

                    saved = tmp_path / "2024" / "week01.json"
                    assert saved.exists()


# ── fetch_matchups_all: partial in-season current_week ───────────────────────


def _fake_matchup():
    """A minimal stand-in for espn_api's BoxScore/Matchup object."""
    matchup = MagicMock()
    matchup.home_team.team_id = 1
    matchup.away_team.team_id = 2
    matchup.home_score = 100.0
    matchup.away_score = 90.0
    matchup.home_projected = 95.0
    matchup.away_projected = 88.0
    matchup.is_playoff = False
    matchup.matchup_type = "NONE"
    return matchup


def test_build_leagues_constructs_one_league_per_season():
    fake_league_2025 = MagicMock()
    fake_league_2026 = MagicMock()

    with patch(
        "leagueintel.ingestion.espn.League",
        side_effect=[fake_league_2025, fake_league_2026],
    ) as mock_league_cls:
        leagues = build_leagues([2025, 2026])

    assert leagues == {2025: fake_league_2025, 2026: fake_league_2026}
    assert mock_league_cls.call_count == 2


def test_fetch_matchups_all_reuses_passed_in_league(tmp_path):
    """
    When a leagues dict is supplied (as sync does), fetch_matchups_all must
    reuse it instead of constructing its own League — that's the whole
    point of sharing one League per season across all fetch_*_all calls.
    """
    fake_league = MagicMock()
    fake_league.finalScoringPeriod = 17
    fake_league.current_week = 1
    fake_league.box_scores.return_value = []

    with patch("leagueintel.ingestion.espn.get_connection") as mock_get_conn:
        with patch("leagueintel.ingestion.espn.create_tables"):
            with patch("leagueintel.ingestion.espn.write_matchups"):
                with patch("leagueintel.ingestion.espn.time.sleep"):
                    with patch(
                        "leagueintel.ingestion.espn.League"
                    ) as mock_league_cls:
                        mock_get_conn.return_value = MagicMock()

                        fetch_matchups_all(
                            seasons=[2026], leagues={2026: fake_league}
                        )

    mock_league_cls.assert_not_called()
    fake_league.box_scores.assert_called_once_with(1)


def test_fetch_matchups_all_only_processes_weeks_through_current_week(
    tmp_path,
):
    """
    Simulates being mid-season: ESPN reports current_week = 5 (the live
    scoringPeriodId) while finalScoringPeriod = 17 (the season's configured
    length, which never changes). fetch_matchups_all must bound by
    current_week, not finalScoringPeriod — otherwise it writes placeholder
    0-score matchup rows for weeks 6-17 that haven't been played yet, which
    corrupts get_max_ingested_week's view of how far the season has
    actually progressed (see waiver.py's history-column "-present" logic).
    """
    fake_league = MagicMock()
    fake_league.finalScoringPeriod = 17
    fake_league.current_week = 5
    fake_league.box_scores.return_value = [_fake_matchup()]

    with patch("leagueintel.ingestion.espn.League", return_value=fake_league):
        with patch("leagueintel.ingestion.espn.get_connection") as mock_get_conn:
            with patch("leagueintel.ingestion.espn.create_tables"):
                with patch("leagueintel.ingestion.espn.write_matchups") as mock_write:
                    with patch("leagueintel.ingestion.espn.time.sleep"):
                        mock_get_conn.return_value = MagicMock()

                        fetch_matchups_all(seasons=[2026])

    weeks_written = [call.args[0][0]["week"] for call in mock_write.call_args_list]
    assert weeks_written == [1, 2, 3, 4, 5]


# ── fetch_box_scores_all: partial in-season current_week ─────────────────────


def test_fetch_box_scores_all_only_processes_weeks_through_current_week():
    """
    Simulates being mid-season: ESPN reports current_week = 5 while
    finalScoringPeriod = 17. In-season, ESPN does NOT raise a KeyError for
    future weeks' box scores — it returns the current roster with 0 points.
    fetch_box_scores_all must bound by current_week, otherwise it writes
    placeholder rows for weeks 6-17, and every currently rostered player
    appears to have played all 17 weeks (with zeros for unplayed ones).
    """
    fake_league = MagicMock()
    fake_league.finalScoringPeriod = 17
    fake_league.current_week = 5

    with patch("leagueintel.ingestion.espn.get_connection") as mock_get_conn:
        with patch("leagueintel.ingestion.espn.create_tables"):
            with patch("leagueintel.ingestion.espn.fetch_box_scores") as mock_fetch:
                with patch("leagueintel.ingestion.espn.write_box_scores"):
                    with patch("leagueintel.ingestion.espn.time.sleep"):
                        mock_get_conn.return_value = MagicMock()
                        mock_fetch.return_value = []

                        fetch_box_scores_all(
                            seasons=[2026], leagues={2026: fake_league}
                        )

    weeks_fetched = [call.args[1] for call in mock_fetch.call_args_list]
    assert weeks_fetched == [1, 2, 3, 4, 5]


# ── unplayed games: NULL instead of 0 ────────────────────────────────────────


def _player(points=12.0, game_played=100, on_bye_week=False, lineup_slot="RB"):
    """
    Stand-in for espn_api's BoxPlayer. game_played is espn_api's own
    signal: 0 until 3h after the player's NFL kickoff, otherwise 100 (bye
    weeks keep the default 100 with on_bye_week=True).
    """
    player = MagicMock()
    player.playerId = 1
    player.name = "Player"
    player.position = "RB"
    player.lineupSlot = lineup_slot
    player.proTeam = "SF"
    player.points = points
    player.projected_points = 10.0
    player.on_bye_week = on_bye_week
    player.game_played = game_played
    return player


def _matchup(home_lineup, away_lineup, has_away_team=True):
    matchup = _fake_matchup()
    matchup.home_lineup = home_lineup
    matchup.away_lineup = away_lineup
    if not has_away_team:
        matchup.away_team = 0  # how espn_api represents a bye
    return matchup


def test_extract_player_week_keeps_points_for_finished_game():
    """Protects the normal case: a finished game's points are stored as-is."""
    assert _extract_player_week(_player(points=12.0), 1, 5, 2026)["points"] == 12.0


def test_extract_player_week_unplayed_game_is_null_not_zero():
    """
    Protects against the reported bug: a player whose game hasn't been
    played (e.g. Browns D/ST before week 7 kicked off) was stored as 0.0,
    so the chatbot said he scored 0. Not played yet must be NULL.
    """
    row = _extract_player_week(_player(points=0.0, game_played=0), 1, 7, 2026)
    assert row["points"] is None


def test_extract_player_week_bye_week_stays_zero():
    """
    Protects bye weeks from being caught by the unplayed rule: a bye is a
    real 0 for the fantasy team, not "not played yet".
    """
    row = _extract_player_week(_player(points=0.0, game_played=100, on_bye_week=True), 1, 7, 2026)
    assert row["points"] == 0.0


def test_extract_matchup_keeps_scores_when_all_starters_finished():
    """
    Protects completed weeks, including past seasons' championships. A
    rule based on current_week would have wiped those, since ESPN reports
    current_week == finalScoringPeriod for a finished season.
    """
    row = _extract_matchup(_matchup([_player()], [_player()]), 17, 2025)
    assert (row["home_score"], row["away_score"]) == (100.0, 90.0)


def test_extract_matchup_scores_null_while_any_starter_unplayed():
    """
    Protects against a partial or not-yet-started week being stored as a
    real score: one starter still to play means neither team's score is
    final, so both are NULL (an unplayed week used to be stored 0.0-0.0).
    """
    row = _extract_matchup(_matchup([_player()], [_player(game_played=0)]), 7, 2026)
    assert (row["home_score"], row["away_score"]) == (None, None)


def test_extract_matchup_ignores_unplayed_bench_players():
    """Protects final scores from bench (and IR) players, who don't count toward the score."""
    home = [_player(), _player(game_played=0, lineup_slot="BE"), _player(game_played=0, lineup_slot="IR")]
    row = _extract_matchup(_matchup(home, [_player()]), 7, 2026)
    assert (row["home_score"], row["away_score"]) == (100.0, 90.0)


def test_extract_matchup_bye_uses_home_lineup_only():
    """Protects bye matchups (no away team, no away lineup) from erroring or being misjudged."""
    row = _extract_matchup(_matchup([_player(game_played=0)], [], has_away_team=False), 7, 2026)
    assert row["away_team_id"] is None
    assert row["home_score"] is None


def test_records_accept_null_scores():
    """Protects the write path: the Pydantic models must let NULL through, not reject or default it to 0."""
    assert BoxScoreRecord(season=2026, week=7, team_id=1, player_id=1, points=None).points is None
    record = MatchupRecord(season=2026, week=7, home_team_id=1, home_score=None, away_score=None)
    assert (record.home_score, record.away_score) == (None, None)
