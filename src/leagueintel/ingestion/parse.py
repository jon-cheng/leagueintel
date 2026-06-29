"""
leagueintel ingestion — parse raw ESPN transaction JSON into structured dicts.

Reads raw JSON files saved by fetch_transactions and extracts:
  - transactions: one record per transaction event
  - transaction_moves: one record per player ADD/DROP within a transaction
"""

import json
from pathlib import Path
from loguru import logger

from leagueintel.config import ALL_SEASONS, DEFAULT_OUTPUT_DIR
from leagueintel.storage.database import get_connection, create_tables
from leagueintel.storage.writer import write_transactions, write_transaction_moves

SKIP_TYPES = {"FUTURE_ROSTER"}


def _extract_transaction(t: dict, season: int) -> dict:
    """Extract transaction fields from a raw ESPN transaction dict."""
    return {
        "id": t["id"],
        "season": season,
        "transaction_type": t.get("type"),
        "status": t.get("status"),
        "bid_amount": t.get("bidAmount", 0),
        "team_id": t.get("teamId"),
        "scoring_period_id": t.get("scoringPeriodId"),
        "execution_type": t.get("executionType"),
        "proposed_date": t.get("proposedDate"),
        "process_date": t.get("processDate"),
        "related_transaction_id": t.get("relatedTransactionId"),
    }


def _extract_moves(t: dict) -> list[dict]:
    """Extract transaction move records from items within a transaction."""
    moves = []
    for item in t.get("items", []):
        moves.append(
            {
                "transaction_id": t["id"],
                "item_type": item.get("type"),
                "player_id": item.get("playerId"),
                "from_team_id": item.get("fromTeamId", 0),
                "to_team_id": item.get("toTeamId", 0),
                "overall_pick_number": item.get("overallPickNumber") or None,
            }
        )
    return moves


def parse_transactions_from_file(
    file_path: Path,
    season: int,
) -> tuple[list[dict], list[dict]]:
    """
    Parse one raw ESPN transaction JSON file.

    Args:
        file_path: path to raw JSON file e.g. data/raw/2024/week08.json
        season: NFL season year

    Returns:
        tuple of (transactions, transaction_moves)
    """
    with open(file_path) as f:
        data = json.load(f)

    transactions = []
    transaction_moves = []

    for t in data.get("transactions", []):
        if t.get("type") in SKIP_TYPES:
            continue
        transactions.append(_extract_transaction(t, season))
        transaction_moves.extend(_extract_moves(t))

    return transactions, transaction_moves


def parse_transactions_all(
    input_dir: str = None,
    seasons: list[int] = None,
) -> None:
    """
    Parse all raw JSON files and write to SQLite.

    Args:
        input_dir: directory containing raw JSON files. Defaults to data/raw/
        seasons: list of seasons to parse. Defaults to ALL_SEASONS
    """
    input_dir = Path(input_dir) if input_dir else DEFAULT_OUTPUT_DIR
    seasons = seasons or ALL_SEASONS

    conn = get_connection()
    create_tables(conn)

    total_transactions = 0
    total_moves = 0

    for season in seasons:
        season_dir = input_dir / str(season)
        if not season_dir.exists():
            logger.warning(f"Season {season}: no data directory at {season_dir}")
            continue

        json_files = sorted(season_dir.glob("week*.json"))
        if not json_files:
            logger.warning(f"Season {season}: no JSON files found")
            continue

        logger.info(f"=== Season {season}: {len(json_files)} files ===")
        season_transactions = []
        season_moves = []

        for file_path in json_files:
            transactions, moves = parse_transactions_from_file(file_path, season)
            season_transactions.extend(transactions)
            season_moves.extend(moves)
            logger.info(
                f"  {file_path.name}: "
                f"{len(transactions)} transactions, "
                f"{len(moves)} moves"
            )

        write_transactions(season_transactions, conn)
        write_transaction_moves(season_moves, conn)

        total_transactions += len(season_transactions)
        total_moves += len(season_moves)
        logger.info(
            f"Season {season}: wrote {len(season_transactions)} transactions, "
            f"{len(season_moves)} moves"
        )

    conn.close()
    logger.info(f"Done. Total: {total_transactions} transactions, {total_moves} moves")
