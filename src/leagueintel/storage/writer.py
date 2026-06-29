"""
SQLite write layer — validates with Pydantic, batch inserts to SQLite.
"""

import sqlite3
from pydantic import BaseModel, ValidationError
from loguru import logger

# ── Pydantic models ───────────────────────────────────────────────────────────


class FantasyTeamSchema(BaseModel):
    season: int
    team_id: int
    team_name: str | None = None
    team_abbrev: str | None = None
    owner_name: str | None = None


class PlayerRecord(BaseModel):
    player_id: int
    full_name: str


class TransactionRecord(BaseModel):
    id: str
    season: int
    transaction_type: str | None = None
    status: str | None = None
    bid_amount: int = 0
    team_id: int | None = None
    scoring_period_id: int | None = None
    execution_type: str | None = None
    proposed_date: int | None = None
    process_date: int | None = None
    related_transaction_id: str | None = None


class TransactionMoveRecord(BaseModel):
    transaction_id: str
    item_type: str | None = None
    player_id: int | None = None
    from_team_id: int = 0
    to_team_id: int = 0
    overall_pick_number: int | None = None


# ── Generic writer ────────────────────────────────────────────────────────────


def _write_records(
    records: list[dict],
    model: type[BaseModel],
    insert_sql: str,
    conn: sqlite3.Connection,
) -> None:
    """Generic writer — validate with Pydantic, batch insert to SQLite."""
    rows = []
    skipped = 0

    for record in records:
        try:
            validated = model(**record)
            rows.append(tuple(validated.model_dump().values()))
        except ValidationError as e:
            logger.warning(f"Skipping invalid record: {e}")
            skipped += 1

    conn.executemany(insert_sql, rows)
    conn.commit()
    logger.info(f"Wrote {len(rows)} records, skipped {skipped}")


# ── Table-specific writers ────────────────────────────────────────────────────


def write_teams(teams: list[dict], conn: sqlite3.Connection) -> None:
    """Write fantasy team records to SQLite."""
    _write_records(
        teams,
        FantasyTeamSchema,
        """
        INSERT OR REPLACE INTO teams
        (season, team_id, team_name, team_abbrev, owner_name)
        VALUES (?, ?, ?, ?, ?)
    """,
        conn,
    )


def write_players(players: list[dict], conn: sqlite3.Connection) -> None:
    """Write player records to SQLite."""
    _write_records(
        players,
        PlayerRecord,
        """
        INSERT OR IGNORE INTO players
        (player_id, full_name)
        VALUES (?, ?)
    """,
        conn,
    )


def write_transactions(transactions: list[dict], conn: sqlite3.Connection) -> None:
    """Write transaction records to SQLite."""
    _write_records(
        transactions,
        TransactionRecord,
        """
        INSERT OR IGNORE INTO transactions
        (id, season, transaction_type, status, bid_amount, team_id,
         scoring_period_id, execution_type, proposed_date, process_date,
         related_transaction_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        conn,
    )


def write_transaction_moves(moves: list[dict], conn: sqlite3.Connection) -> None:
    """Write transaction move records — excludes auto-generated id."""
    rows = []
    skipped = 0

    for move in moves:
        try:
            record = TransactionMoveRecord(**move)
            rows.append(
                (
                    record.transaction_id,
                    record.item_type,
                    record.player_id,
                    record.from_team_id,
                    record.to_team_id,
                    record.overall_pick_number,
                )
            )
        except ValidationError as e:
            logger.warning(f"Skipping invalid move: {e}")
            skipped += 1

    conn.executemany(
        """
        INSERT OR IGNORE INTO transaction_moves
        (transaction_id, item_type, player_id, from_team_id,
         to_team_id, overall_pick_number)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        rows,
    )
    conn.commit()
    logger.info(f"Wrote {len(rows)} transaction moves, skipped {skipped}")
