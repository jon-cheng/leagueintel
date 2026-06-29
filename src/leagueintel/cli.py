"""
leagueintel CLI

Usage:
    leagueintel fetch-transactions --year 2024 --week 1
    leagueintel fetch-transactions --year 2024
    leagueintel fetch-transactions
    leagueintel fetch-teams --seasons 2024
    leagueintel fetch-teams
"""

import click
from leagueintel.ingestion.espn import fetch_transactions_all, fetch_teams_all


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
        year=year,
        week=week,
        max_week=max_week,
        output_dir=output_dir,
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


if __name__ == "__main__":
    cli()
