# storage/database.py
import sqlite3
from pathlib import Path
from dotenv import find_dotenv

REPO_ROOT = Path(find_dotenv()).parent
DEFAULT_DB_PATH = REPO_ROOT / "leagueintel.db"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Return a SQLite connection to the leagueintel database."""
    return sqlite3.connect(db_path)


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all leagueintel tables if they don't exist."""
    _create_teams_table(conn)
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
