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


def test_fetch_transactions_all_saves_file(sample_response, tmp_path):
    with patch("leagueintel.ingestion.espn.LEAGUE_ID", "123"):
        with patch("leagueintel.ingestion.espn.ESPN_S2", "abc"):
            with patch("leagueintel.ingestion.espn.SWID", "{xyz}"):
                with patch("leagueintel.ingestion.espn._fetch_week") as mock_fetch:
                    mock_fetch.return_value = sample_response

                    fetch_transactions_all(year=2024, week=1, output_dir=str(tmp_path))

                    saved = tmp_path / "2024" / "week01.json"
                    assert saved.exists()
