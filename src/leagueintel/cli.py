"""
leagueintel CLI

Usage:
    leagueintel fetch-transactions --year 2024 --week 1
    leagueintel fetch-transactions --year 2024
    leagueintel fetch-transactions
"""

import click
from leagueintel.ingestion.espn import fetch_transactions_all


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
    help="Week number (1-17). If omitted, fetches all weeks.",
)
@click.option(
    "--output-dir",
    type=str,
    default=None,
    help="Output directory for raw JSON. Defaults to data/raw/.",
)
def fetch_transactions(year, week, output_dir):
    """Fetch ESPN transaction data and save as raw JSON."""
    fetch_transactions_all(year=year, week=week, output_dir=output_dir)


if __name__ == "__main__":
    cli()
