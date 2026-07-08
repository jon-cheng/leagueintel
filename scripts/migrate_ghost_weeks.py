"""
One-time migration: delete ghost week rows from matchups and box_scores.

Pre-2021 ESPN seasons stored the championship matchup in both week 16 and week 17
with identical data. We now use league.finalScoringPeriod at ingestion time to
cap the week range correctly, but this script cleans up rows already in the DB.

Usage (local):
    poetry run python scripts/migrate_ghost_weeks.py

Usage (against S3/prod DB):
    Set DB_PATH=/tmp/leagueintel.db and download/upload manually, or
    run migrate_db.py first to pull the DB, then run this script.
"""

from espn_api.football import League
from loguru import logger
from leagueintel.config import LEAGUE_ID, ESPN_S2, SWID, ALL_SEASONS
from leagueintel.storage.database import get_connection


def delete_ghost_weeks(conn, season: int, final_week: int) -> None:
    matchup_rows = conn.execute(
        "SELECT COUNT(*) FROM matchups WHERE season = ? AND week > ?",
        (season, final_week),
    ).fetchone()[0]

    box_score_rows = conn.execute(
        "SELECT COUNT(*) FROM box_scores WHERE season = ? AND week > ?",
        (season, final_week),
    ).fetchone()[0]

    if matchup_rows == 0 and box_score_rows == 0:
        logger.info(f"Season {season}: no ghost rows found (finalScoringPeriod={final_week})")
        return

    conn.execute(
        "DELETE FROM matchups WHERE season = ? AND week > ?",
        (season, final_week),
    )
    conn.execute(
        "DELETE FROM box_scores WHERE season = ? AND week > ?",
        (season, final_week),
    )
    logger.info(
        f"Season {season}: deleted {matchup_rows} matchup row(s) and "
        f"{box_score_rows} box_score row(s) beyond week {final_week}"
    )


def main():
    conn = get_connection()

    for year in ALL_SEASONS:
        league = League(league_id=LEAGUE_ID, year=year, espn_s2=ESPN_S2, swid=SWID)
        delete_ghost_weeks(conn, season=year, final_week=league.finalScoringPeriod)

    conn.commit()
    conn.close()
    logger.info("Migration complete.")


if __name__ == "__main__":
    main()
