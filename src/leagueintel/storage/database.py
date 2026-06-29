"""
SQLite database connection and schema management.
"""

import sqlite3
from pathlib import Path
from leagueintel.config import DEFAULT_DB_PATH


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Return a SQLite connection to the leagueintel database."""
    return sqlite3.connect(db_path)


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all leagueintel tables if they don't exist."""
    _create_teams_table(conn)
    _create_players_table(conn)
    _create_transactions_table(conn)
    _create_transaction_moves_table(conn)
    _create_box_scores_table(conn)
    conn.commit()


def _create_teams_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            team_id INTEGER,
            season INTEGER,
            team_name TEXT,
            team_abbrev TEXT,
            owner_name TEXT,
            PRIMARY KEY (team_id, season)
        )
    """)


def _create_players_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL
        )
    """)


def _create_transactions_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            season INTEGER NOT NULL,
            transaction_type TEXT,
            status TEXT,
            bid_amount INTEGER,
            team_id INTEGER,
            scoring_period_id INTEGER,
            execution_type TEXT,
            proposed_date INTEGER,
            process_date INTEGER,
            related_transaction_id TEXT,
            FOREIGN KEY (team_id) REFERENCES teams(team_id)
        )
    """)


def _create_transaction_moves_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transaction_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT NOT NULL,
            item_type TEXT,
            player_id INTEGER,
            from_team_id INTEGER,
            to_team_id INTEGER,
            overall_pick_number INTEGER,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)


def _create_box_scores_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS box_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            player_name TEXT,
            position TEXT,
            lineup_slot TEXT,
            pro_team TEXT,
            points REAL,
            projected_points REAL,
            on_bye_week INTEGER,
            game_played INTEGER,
            FOREIGN KEY (team_id) REFERENCES teams(team_id),
            FOREIGN KEY (player_id) REFERENCES players(player_id),
            UNIQUE (season, week, player_id)
        )
    """)
