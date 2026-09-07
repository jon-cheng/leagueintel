"""
SQLite database connection and schema management.

Cloud freshness
---------------
On Streamlit Community Cloud the DB is a snapshot pulled from S3. A daily
cron job uploads a fresh ``leagueintel.db``; there's no API to reboot the
app to pick it up, so instead the app checks the S3 ETag (cheap
``head_object``, at most once every 10 minutes) and re-downloads only when
it changed. Each snapshot lands in its own ``/tmp/leagueintel_<etag>.db``
so an in-flight query on an older file never has it yanked mid-read.

Local development is unaffected: ``_in_cloud()`` is False, so
``get_connection()`` opens the repo's ``leagueintel.db`` directly with no
S3 calls.
"""

import glob
import os
import sqlite3
from pathlib import Path

import boto3
import streamlit as st

from leagueintel.config import DEFAULT_DB_PATH, S3_BUCKET, S3_KEY

# where per-etag snapshots are written on the cloud container; patched in tests
SNAPSHOT_DIR = "/tmp"


def _in_cloud() -> bool:
    """True on the Streamlit Cloud container (DB_PATH points at /tmp)."""
    return str(DEFAULT_DB_PATH).startswith("/tmp")


def _s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-west-2"),
    )


@st.cache_data(ttl="10m")
def get_current_etag() -> str | None:
    """
    Current S3 ETag of leagueintel.db — metadata only, no download.

    Cached for 10 minutes so a burst of reruns / chat messages triggers at
    most one head_object per 10 min. Returns None in local development.
    """
    if not _in_cloud():
        return None
    head = _s3_client().head_object(Bucket=S3_BUCKET, Key=S3_KEY)
    return head["ETag"].strip('"')


@st.cache_resource(max_entries=3)
def _download_snapshot(etag: str) -> str:
    """
    Download the S3 DB snapshot for ``etag`` to a unique local path and
    return it. Memoized per-etag: an unchanged etag is an instant cache
    hit (no S3 call); a new etag (cron uploaded a fresh DB) misses and
    triggers a real download. max_entries=3 keeps the 3 most-recently-used
    snapshot paths resident, LRU-evicting older ones.
    """
    dest = os.path.join(SNAPSHOT_DIR, f"leagueintel_{etag[:8]}.db")
    if not os.path.exists(dest):
        _s3_client().download_file(S3_BUCKET, S3_KEY, dest)
    _prune_snapshots(keep=3)
    return dest


def _prune_snapshots(keep: int = 3) -> None:
    """
    Delete all but the ``keep`` most recent (by mtime) snapshot files.
    A file still open by another session raises OSError on Windows and is
    silently skipped — it'll be retried on the next prune.
    """
    paths = sorted(
        glob.glob(os.path.join(SNAPSHOT_DIR, "leagueintel_*.db")),
        key=os.path.getmtime,
        reverse=True,
    )
    for stale in paths[keep:]:
        try:
            os.remove(stale)
        except OSError:
            pass


def resolve_db_path() -> str:
    """
    Path to the freshest local copy of the DB. Re-downloads from S3 only
    when the ETag changed; otherwise returns the cached snapshot path
    instantly. Falls back to the local repo DB when not on the cloud.
    """
    etag = get_current_etag()
    if etag is None:
        return str(DEFAULT_DB_PATH)
    return _download_snapshot(etag)


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """
    Return a SQLite connection to the leagueintel database.

    With no argument it resolves the freshest DB (see ``resolve_db_path``);
    pass an explicit ``db_path`` to bypass that (used by ingestion/tests).
    """
    if db_path is None:
        db_path = resolve_db_path()
    return sqlite3.connect(db_path)


def get_max_ingested_week(conn: sqlite3.Connection, season: int) -> int:
    """Return the latest week with matchup data ingested for a season, or 0 if none."""
    row = conn.execute(
        "SELECT MAX(week) FROM matchups WHERE season = ?", (season,)
    ).fetchone()
    return row[0] or 0


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all leagueintel tables if they don't exist."""
    _create_teams_table(conn)
    _create_players_table(conn)
    _create_transactions_table(conn)
    _create_transaction_moves_table(conn)
    _create_box_scores_table(conn)
    _create_matchups_table(conn)
    _create_season_settings_table(conn)
    conn.commit()


def _create_teams_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            team_id INTEGER,
            season INTEGER,
            team_name TEXT,
            team_abbrev TEXT,
            owner_name TEXT,
            standing INTEGER,
            final_standing INTEGER,
            PRIMARY KEY (team_id, season)
        )
    """)
    # migration for DBs created before standing/final_standing existed
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(teams)")}
    if "standing" not in existing_columns:
        conn.execute("ALTER TABLE teams ADD COLUMN standing INTEGER")
    if "final_standing" not in existing_columns:
        conn.execute("ALTER TABLE teams ADD COLUMN final_standing INTEGER")


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
            source TEXT NOT NULL DEFAULT 'ESPN',
            FOREIGN KEY (transaction_id) REFERENCES transactions(id),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    # migration for DBs created before the source column existed
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(transaction_moves)")
    }
    if "source" not in existing_columns:
        conn.execute(
            "ALTER TABLE transaction_moves ADD COLUMN source TEXT NOT NULL DEFAULT 'ESPN'"
        )


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


def _create_season_settings_table(conn: sqlite3.Connection) -> None:
    """
    Per-season league settings that aren't per-team — currently just
    median_scoring (ESPN's "Bonus Wins and Losses" rule), read from
    league.settings.median_scoring at ingestion time. A season's rules
    can change year to year (this league is adding median scoring for
    2026), so this is keyed by season, not a single global flag.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS season_settings (
            season INTEGER PRIMARY KEY,
            median_scoring INTEGER NOT NULL DEFAULT 0
        )
    """)


def _create_matchups_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS matchups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season INTEGER NOT NULL,           -- NFL season year
            week INTEGER NOT NULL,             -- NFL week number 1-17
            home_team_id INTEGER NOT NULL,     -- references teams.team_id
            away_team_id INTEGER,              -- NULL = bye week
            home_score REAL,                   -- actual points scored
            away_score REAL,                   -- actual points scored, 0 if bye
            home_projected REAL,               -- projected points before games
            away_projected REAL,
            is_playoff INTEGER,                -- 0 or 1
            matchup_type TEXT,                 -- NONE=regular season,
                                                -- WINNERS_BRACKET=championship bracket,
                                                -- WINNERS_CONSOLATION_LADDER=3rd-6th place games,
                                                -- LOSERS_CONSOLATION_LADDER=bottom bracket
            FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
            FOREIGN KEY (away_team_id) REFERENCES teams(team_id),
            UNIQUE (season, week, home_team_id, away_team_id)
        )
    """)
