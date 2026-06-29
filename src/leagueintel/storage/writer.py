from pydantic import BaseModel, ValidationError
from loguru import logger
import sqlite3


class FantasyTeamSchema(BaseModel):
    season: int
    team_id: int
    team_name: str | None = None
    team_abbrev: str | None = None
    owner_name: str | None = None


def _populate_row(team: dict) -> tuple | None:
    try:
        record = FantasyTeamSchema(**team)
        return (
            record.season,
            record.team_id,
            record.team_name,
            record.team_abbrev,
            record.owner_name,
        )
    except ValidationError as e:
        logger.warning(f"Skipping invalid team record: {e}")
        return None


def write_teams(teams: list[dict], conn: sqlite3.Connection) -> None:
    rows = [_populate_row(team) for team in teams]
    rows = [row for row in rows if row is not None]  # filter failed validations
    conn.executemany(
        """
        INSERT OR REPLACE INTO teams 
        (season, team_id, team_name, team_abbrev, owner_name)
        VALUES (?, ?, ?, ?, ?)
    """,
        rows,
    )
    conn.commit()
    logger.info(f"Wrote {len(rows)} team records")
