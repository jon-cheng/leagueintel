# scripts/anonymize_demo_db.py
"""
One-time, in-place anonymization of a DISPOSABLE COPY of the database, for
taking anonymized screenshots/demos. See README "Taking anonymized
screenshots" for the full workflow.

This is NOT a schema migration. It permanently overwrites
teams.owner_name and teams.team_name with generated aliases (US
presidents and pun team names, see ALIASES below) directly in the teams
table of whatever --db file you point it at. No view, no sidecar table,
nothing read at runtime by the app — once this runs, the file simply
contains alias strings as if they'd always been there.

SAFETY: only ever run this against a SEPARATE disposable copy of the
database — never the real leagueintel.db, never production. --db is
required (no default, no fallback to config.DB_PATH) specifically so
this can't accidentally run against whatever DB the app is currently
configured to use. This UPDATE is irreversible except by re-copying the
original file.

Usage:
    poetry run python scripts/anonymize_demo_db.py --db ./leagueintel_demo.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path


ALIASES = [
    ("George Washington", "Crossing the Delaware"),
    ("Abraham Lincoln", "Four Score Seven Yards Ago"),
    ("Thomas Jefferson", "Louisiana Purchasers"),
    ("Theodore Roosevelt", "Teddy Bears"),
    ("Franklin Roosevelt", "Fourth & Term"),
    ("Andrew Jackson", "Twenty Dollar Bills"),
    ("Herbert Hoover", "Hooverville Heroes"),
    ("Dwight Eisenhower", "Highway Robbery"),
    ("Woodrow Wilson", "Fourteen Points, Zero Rings"),
    ("Harry Truman", "The Buck Stops Here"),
    ("James Madison", "Federalist Force"),
    ("John F. Kennedy", "Bay of Pigskin"),
    ("Ronald Reagan", "Trickle-Down Touchdowns"),
    ("Calvin Coolidge", "Silent But Deadly"),
]


def _alias_for(index: int) -> tuple[str, str]:
    """
    index 0-13 -> ALIASES in order. Beyond that, cycle through ALIASES
    again with a " II"/" III"/... suffix on both names, so this doesn't
    hard-fail if the league ever grows past len(ALIASES) teams — unlikely
    at this league's scale, but a hard error here would block the whole
    script over a cosmetic edge case.
    """
    owner, team = ALIASES[index % len(ALIASES)]
    cycle = index // len(ALIASES)
    if cycle == 0:
        return owner, team
    suffix = " " + "I" * (cycle + 1) if cycle < 3 else f" ({cycle + 1})"
    return owner + suffix, team + suffix


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Permanently overwrite owner_name/team_name with aliases "
        "in a disposable copy of leagueintel.db"
    )
    parser.add_argument(
        "--db", required=True, help="Path to the disposable demo database file (required, no default)"
    )
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Bypass the 'demo' filename safety check",
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    print(f"Resolved database path: {db_path}")

    if not db_path.exists():
        print(f"Error: {db_path} does not exist.")
        sys.exit(1)

    if "demo" not in db_path.name.lower() and not args.i_know_what_im_doing:
        print(
            f"Error: '{db_path.name}' does not contain 'demo' — refusing to run.\n"
            "This script permanently overwrites real names in place. It must only "
            "ever run against a separate disposable copy, never the real "
            "leagueintel.db or production. Pass --i-know-what-im-doing to override."
        )
        sys.exit(1)

    conn = sqlite3.connect(db_path)

    row_count = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    sample = conn.execute(
        "SELECT DISTINCT owner_name FROM teams ORDER BY owner_name LIMIT 5"
    ).fetchall()
    print(f"\nteams table has {row_count} rows.")
    print("Sample of current owner_name values:")
    for (name,) in sample:
        print(f"  {name}")

    confirm = input(
        f"\nThis will PERMANENTLY overwrite real names in {db_path} "
        f"({row_count} teams). This cannot be undone except by re-copying "
        f"the original file. Type 'yes' to continue: "
    )
    if confirm != "yes":
        print("Aborted.")
        conn.close()
        sys.exit(1)

    team_ids = [
        row[0]
        for row in conn.execute("SELECT DISTINCT team_id FROM teams ORDER BY team_id")
    ]
    aliases = {team_id: _alias_for(i) for i, team_id in enumerate(team_ids)}

    with conn:
        for team_id, (owner_alias, team_alias) in aliases.items():
            conn.execute(
                """
                UPDATE teams
                SET owner_name = ?, team_name = ?
                WHERE team_id = ?
                """,
                (owner_alias, team_alias, team_id),
            )

    # verify: each team_id maps to exactly one owner_name/team_name across
    # every season row it appears in
    mismatches = conn.execute("""
        SELECT team_id, COUNT(DISTINCT owner_name), COUNT(DISTINCT team_name)
        FROM teams
        GROUP BY team_id
        HAVING COUNT(DISTINCT owner_name) > 1 OR COUNT(DISTINCT team_name) > 1
    """).fetchall()
    if mismatches:
        print("\nERROR: inconsistent aliasing detected across seasons for team_id(s):")
        for team_id, n_owner, n_team in mismatches:
            print(f"  team_id={team_id}: {n_owner} distinct owner_name, {n_team} distinct team_name")
        conn.close()
        sys.exit(1)

    print(f"\nVerified: all {len(team_ids)} team_id(s) map to exactly one alias across every season row.")

    final_mapping = conn.execute(
        "SELECT DISTINCT team_id, owner_name FROM teams ORDER BY team_id"
    ).fetchall()
    conn.close()

    print("\nteam_id -> alias:")
    for team_id, owner_name in final_mapping:
        print(f"  {team_id} -> {owner_name}")


if __name__ == "__main__":
    main()
