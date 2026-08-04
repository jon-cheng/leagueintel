# tests/test_cli.py
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from leagueintel.cli import cli


def test_sync_runs_full_pipeline_including_transactions():
    """
    sync must fetch+parse transactions alongside teams/players/box scores/
    matchups — this pipeline stage was previously left out, which is why
    the transactions table went stale (only ever populated by a manual,
    undocumented one-off run of fetch-transactions + parse-transactions).
    """
    fake_leagues = {2026: MagicMock()}
    with patch("leagueintel.cli.build_leagues", return_value=fake_leagues):
        with patch("leagueintel.cli.fetch_teams_all") as mock_teams:
            with patch("leagueintel.cli.fetch_players_all") as mock_players:
                with patch(
                    "leagueintel.cli.fetch_box_scores_all"
                ) as mock_box_scores:
                    with patch(
                        "leagueintel.cli.fetch_matchups_all"
                    ) as mock_matchups:
                        with patch(
                            "leagueintel.cli.fetch_transactions_all"
                        ) as mock_fetch_txns:
                            with patch(
                                "leagueintel.cli.parse_transactions_all"
                            ) as mock_parse_txns:
                                with patch(
                                    "leagueintel.cli.infer_missing_trade_items_all"
                                ) as mock_infer_trades:
                                    runner = CliRunner()
                                    result = runner.invoke(
                                        cli, ["sync", "--seasons", "2026"]
                                    )

    assert result.exit_code == 0
    mock_teams.assert_called_once_with(seasons=[2026], leagues=fake_leagues)
    mock_players.assert_called_once_with(seasons=[2026], leagues=fake_leagues)
    mock_box_scores.assert_called_once_with(seasons=[2026], leagues=fake_leagues)
    mock_matchups.assert_called_once_with(seasons=[2026], leagues=fake_leagues)
    mock_fetch_txns.assert_called_once_with(year=2026, leagues=fake_leagues)
    mock_parse_txns.assert_called_once_with(seasons=[2026])
    mock_infer_trades.assert_called_once_with(seasons=[2026])


def test_sync_builds_one_league_dict_shared_across_all_steps():
    """
    Each League(...) construction is its own ESPN API call. sync should
    build the leagues dict exactly once per run and pass the same object
    into every fetch step, rather than each step rebuilding its own.
    """
    fake_leagues = {2026: MagicMock()}
    with patch(
        "leagueintel.cli.build_leagues", return_value=fake_leagues
    ) as mock_build:
        with patch("leagueintel.cli.fetch_teams_all"):
            with patch("leagueintel.cli.fetch_players_all"):
                with patch("leagueintel.cli.fetch_box_scores_all"):
                    with patch("leagueintel.cli.fetch_matchups_all"):
                        with patch("leagueintel.cli.fetch_transactions_all"):
                            with patch("leagueintel.cli.parse_transactions_all"):
                                with patch(
                                    "leagueintel.cli.infer_missing_trade_items_all"
                                ):
                                    runner = CliRunner()
                                    runner.invoke(
                                        cli, ["sync", "--seasons", "2026"]
                                    )

    mock_build.assert_called_once_with([2026])


def test_sync_with_no_seasons_fetches_transactions_for_all_seasons():
    with patch("leagueintel.cli.build_leagues", return_value={}):
        with patch("leagueintel.cli.fetch_teams_all"):
            with patch("leagueintel.cli.fetch_players_all"):
                with patch("leagueintel.cli.fetch_box_scores_all"):
                    with patch("leagueintel.cli.fetch_matchups_all"):
                        with patch(
                            "leagueintel.cli.fetch_transactions_all"
                        ) as mock_fetch_txns:
                            with patch(
                                "leagueintel.cli.parse_transactions_all"
                            ) as mock_parse_txns:
                                with patch(
                                    "leagueintel.cli.infer_missing_trade_items_all"
                                ) as mock_infer_trades:
                                    runner = CliRunner()
                                    result = runner.invoke(cli, ["sync"])

    assert result.exit_code == 0
    mock_fetch_txns.assert_called_once_with(leagues={})
    mock_parse_txns.assert_called_once_with(seasons=None)
    mock_infer_trades.assert_called_once_with(seasons=None)


def test_infer_trades_command_passes_seasons_list():
    with patch(
        "leagueintel.cli.infer_missing_trade_items_all"
    ) as mock_infer_trades:
        runner = CliRunner()
        result = runner.invoke(cli, ["infer-trades", "--seasons", "2024"])

    assert result.exit_code == 0
    mock_infer_trades.assert_called_once_with(seasons=[2024])


def test_infer_trades_command_with_no_seasons_passes_none():
    with patch(
        "leagueintel.cli.infer_missing_trade_items_all"
    ) as mock_infer_trades:
        runner = CliRunner()
        result = runner.invoke(cli, ["infer-trades"])

    assert result.exit_code == 0
    mock_infer_trades.assert_called_once_with(seasons=None)
