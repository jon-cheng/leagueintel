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
    build_leagues,
)


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


# ── fetch_matchups_all: partial in-season finalScoringPeriod ─────────────────


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
    fake_league.finalScoringPeriod = 1
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


def test_fetch_matchups_all_only_processes_weeks_through_final_scoring_period(
    tmp_path,
):
    """
    Simulates being mid-season: ESPN reports finalScoringPeriod = 5, meaning
    only 5 weeks have occurred so far. fetch_matchups_all should stop there
    instead of trying (and failing on) weeks 6+, which don't exist yet.
    """
    fake_league = MagicMock()
    fake_league.finalScoringPeriod = 5
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
