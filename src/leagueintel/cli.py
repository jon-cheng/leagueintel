"""
leagueintel CLI

Usage:
    leagueintel fetch-transactions --year 2024 --week 1
    leagueintel fetch-transactions --year 2024
    leagueintel fetch-transactions
    leagueintel fetch-teams --seasons 2024
    leagueintel fetch-teams
    leagueintel fetch-players --seasons 2024
    leagueintel fetch-players
    leagueintel parse-transactions --seasons 2024
    leagueintel parse-transactions
    leagueintel fetch-box-scores [--seasons 2024]
    leagueintel fetch-matchups [--seasons 2024]
"""

import click
from leagueintel.ingestion.espn import (
    fetch_transactions_all,
    fetch_teams_all,
    fetch_players_all,
    fetch_box_scores_all,
    fetch_matchups_all,
)
from leagueintel.ingestion.parse import parse_transactions_all


@click.group()
def cli():
    """leagueintel — fantasy football analytics and competitive intelligence."""
    pass


@cli.command()
@click.option(
    "--year",
    type=int,
    default=None,
    help="Season year to fetch. If omitted, fetches all seasons.",
)
@click.option(
    "--week",
    type=int,
    default=None,
    help="Specific week number to fetch. If omitted, fetches all weeks.",
)
@click.option(
    "--max-week",
    type=int,
    default=17,
    show_default=True,
    help="Maximum week number to fetch.",
)
@click.option(
    "--output-dir",
    type=str,
    default=None,
    help="Output directory for raw JSON. Defaults to data/raw/.",
)
def fetch_transactions(year, week, max_week, output_dir):
    """Fetch ESPN transaction data and save as raw JSON."""
    fetch_transactions_all(
        year=year, week=week, max_week=max_week, output_dir=output_dir
    )


@cli.command()
@click.option(
    "--seasons",
    multiple=True,
    type=int,
    default=None,
    help="Seasons to fetch. If omitted, fetches all seasons.",
)
def fetch_teams(seasons):
    """Fetch ESPN fantasy team data and write to SQLite."""
    fetch_teams_all(seasons=list(seasons) if seasons else None)


@cli.command()
@click.option(
    "--seasons",
    multiple=True,
    type=int,
    default=None,
    help="Seasons to fetch. If omitted, fetches all seasons.",
)
def fetch_players(seasons):
    """Fetch ESPN player map and write to SQLite."""
    fetch_players_all(seasons=list(seasons) if seasons else None)


@cli.command()
@click.option(
    "--seasons",
    multiple=True,
    type=int,
    default=None,
    help="Seasons to parse. If omitted, parses all seasons.",
)
@click.option(
    "--input-dir",
    type=str,
    default=None,
    help="Input directory for raw JSON. Defaults to data/raw/.",
)
def parse_transactions(seasons, input_dir):
    """Parse raw ESPN JSON files and write transactions to SQLite."""
    parse_transactions_all(
        seasons=list(seasons) if seasons else None,
        input_dir=input_dir,
    )


@cli.command()
@click.option(
    "--seasons",
    multiple=True,
    type=int,
    default=None,
    help="Seasons to fetch. If omitted, fetches all seasons.",
)
def fetch_box_scores(seasons):
    """Fetch ESPN box score data and write to SQLite."""
    fetch_box_scores_all(seasons=list(seasons) if seasons else None)


@cli.command()
@click.option(
    "--seasons",
    multiple=True,
    type=int,
    default=None,
    help="Seasons to fetch. If omitted, fetches all seasons.",
)
def fetch_matchups(seasons):
    """Fetch ESPN matchup results and write to SQLite."""
    fetch_matchups_all(seasons=list(seasons) if seasons else None)


if __name__ == "__main__":
    cli()
