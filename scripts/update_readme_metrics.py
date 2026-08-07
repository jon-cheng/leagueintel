# scripts/update_readme_metrics.py
"""
Recompute the "Live metrics from my league" table in README.md from the
current leagueintel.db and rewrite it in place between the
METRICS_TABLE_START/END markers. Owner names are already anonymized
(US Presidents) at the DB level, so no extra scrubbing is needed here.

Usage:
    poetry run python scripts/update_readme_metrics.py
"""

import re
import sqlite3
from datetime import datetime, timezone

from leagueintel.config import ALL_SEASONS, DEFAULT_DB_PATH, REPO_ROOT

README_PATH = REPO_ROOT / "README.md"
START_MARKER = "<!-- METRICS_TABLE_START -->"
END_MARKER = "<!-- METRICS_TABLE_END -->"


def _fetch_metrics(conn: sqlite3.Connection) -> dict:
    min_season, max_season, num_seasons = conn.execute(
        "SELECT MIN(season), MAX(season), COUNT(DISTINCT season) FROM teams"
    ).fetchone()

    last_completed_season = max_season - 1
    num_current_managers = conn.execute(
        "SELECT COUNT(DISTINCT owner_name) FROM teams WHERE season = ?",
        (last_completed_season,),
    ).fetchone()[0]

    num_players = conn.execute(
        "SELECT COUNT(DISTINCT player_id) FROM box_scores"
    ).fetchone()[0]

    num_bids, num_adds = conn.execute(
        """
        SELECT
            COUNT(*),
            SUM(CASE WHEN status = 'EXECUTED' THEN 1 ELSE 0 END)
        FROM transactions
        WHERE transaction_type = 'WAIVER' AND bid_amount IS NOT NULL
        """
    ).fetchone()

    num_matchups = conn.execute(
        "SELECT COUNT(*) FROM matchups WHERE away_team_id IS NOT NULL"
    ).fetchone()[0]

    return {
        "seasons": f"{min_season}-{max_season}",
        "seasons_count": num_seasons,
        "rich_data_seasons": f"{min(ALL_SEASONS)}-{max(ALL_SEASONS)}",
        "rich_data_seasons_count": len(ALL_SEASONS),
        "current_managers": num_current_managers,
        "players": num_players,
        "bids": num_bids,
        "adds": num_adds,
        "matchups": num_matchups,
    }


def _stat_cell(value, label: str) -> str:
    return (
        "<td align=\"center\">\n"
        f"<h3>{value}</h3>\n"
        f"<sub>{label}</sub>\n"
        "</td>"
    )


def _stat_row(cells: list[str]) -> str:
    return "<tr>\n" + "\n".join(cells) + "\n</tr>"


def _render_stat_grid(m: dict) -> str:
    stats = [
        (f"{m['seasons']} ({m['seasons_count']})", "Seasons"),
        (
            f"{m['rich_data_seasons']} ({m['rich_data_seasons_count']})",
            "Rich-Data Seasons",
        ),
        (m["current_managers"], "Current Managers"),
        (m["players"], "Rostered Players"),
        (f"{m['bids']:,}", "Waiver Bids Placed"),
        (f"{m['adds']:,}", "Successful Adds"),
        (m["matchups"], "Matchups Played"),
    ]

    cells = [_stat_cell(value, label) for value, label in stats]
    row_size = 4
    rows = [
        _stat_row(cells[i : i + row_size])
        for i in range(0, len(cells), row_size)
    ]

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M GMT")

    lines = [
        START_MARKER,
        '<table align="center">',
        *rows,
        "</table>",
        "",
        "<p align=\"center\"><sub><i>Current season in progress — "
        "figures reflect all completed data.</i></sub></p>",
        f'<p align="center"><sub>Last updated: {updated_at}</sub></p>',
        END_MARKER,
    ]
    return "\n".join(lines)


def main() -> None:
    conn = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
    metrics = _fetch_metrics(conn)
    conn.close()

    table = _render_stat_grid(metrics)

    readme = README_PATH.read_text()
    pattern = re.compile(
        re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL
    )
    if not pattern.search(readme):
        raise ValueError(
            f"Could not find {START_MARKER}...{END_MARKER} block in README.md"
        )

    updated = pattern.sub(table, readme)
    README_PATH.write_text(updated)
    print("README.md metrics table updated")


if __name__ == "__main__":
    main()
