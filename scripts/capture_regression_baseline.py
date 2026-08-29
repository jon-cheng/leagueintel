# scripts/capture_regression_baseline.py
"""
Captures a regression baseline: for every season in ALL_SEASONS, calls the
six core analytics entry points against the REAL leagueintel.db and
serializes the results to tests/fixtures/regression_baseline.json.

This baseline exists so an upcoming refactor (making standings/draft/waiver
analytics driven by ESPN league settings instead of hardcoded assumptions)
can be checked against real historical output, not just synthetic fixtures.
See tests/analytics/test_regression_baseline.py for the test that diffs
against this file.

owner_name/team_name are pseudonymized before writing (manager_1, team_1,
...) so real people's names never land in a committed fixture. The mapping
is rebuilt fresh each run from teams.team_id (stable across seasons for the
same manager, per anonymize_demo_db.py's own verification query) — nothing
about the real mapping itself is persisted anywhere.

Usage:
    poetry run python scripts/capture_regression_baseline.py
"""

import json
import sqlite3
from pathlib import Path

from leagueintel.analytics.availability import SeasonNotReadyError
from leagueintel.analytics.consolation import (
    get_arbys_winner,
    get_medal_standings,
    get_toilet_bowl_loser,
)
from leagueintel.analytics.draft import get_draft_roi
from leagueintel.analytics.standings import get_standings
from leagueintel.analytics.waiver import get_waiver_scores
from leagueintel.config import ALL_SEASONS, DEFAULT_DB_PATH, REPO_ROOT

OUTPUT_PATH = REPO_ROOT / "tests" / "fixtures" / "regression_baseline.json"

# fields known to carry real owner/team names, per function — see
# GENERALIZATION_PLAN.md step 1 for how this was enumerated
NAME_FIELDS = {
    "get_standings": {"manager": "owner"},
    "get_medal_standings": {"first": "owner", "second": "owner", "third": "owner"},
    "get_arbys_winner": {"arbys_winner": "owner", "opponent": "owner"},
    "get_toilet_bowl_loser": {"last_place": "owner", "opponent": "owner"},
    "get_draft_roi": {"owner_name": "owner"},
    "get_waiver_scores": {"owner_name": "owner", "team_name": "team"},
}

FUNCTIONS = {
    "get_standings": get_standings,
    "get_medal_standings": get_medal_standings,
    "get_arbys_winner": get_arbys_winner,
    "get_toilet_bowl_loser": get_toilet_bowl_loser,
    "get_draft_roi": get_draft_roi,
    "get_waiver_scores": get_waiver_scores,
}


def build_pseudonym_maps(db_path: Path) -> tuple[dict, dict]:
    """
    Build owner_name -> "manager_N" and team_name -> "team_N" maps.

    Owners are numbered by team_id order (stable identity across seasons
    for the same manager). Team names are numbered alphabetically (a
    manager's team name changes every season, so there's no stable
    per-manager identity to key off for these — alphabetical just keeps
    the numbering deterministic run-to-run).
    """
    conn = sqlite3.connect(db_path)
    owner_rows = conn.execute(
        "SELECT DISTINCT team_id, owner_name FROM teams ORDER BY team_id"
    ).fetchall()
    team_name_rows = conn.execute(
        "SELECT DISTINCT team_name FROM teams ORDER BY team_name"
    ).fetchall()
    conn.close()

    owner_map = {
        owner_name: f"manager_{i + 1}" for i, (_, owner_name) in enumerate(owner_rows)
    }
    team_name_map = {
        team_name: f"team_{i + 1}" for i, (team_name,) in enumerate(team_name_rows)
    }
    return owner_map, team_name_map


def pseudonymize_value(value, kind: str, owner_map: dict, team_name_map: dict):
    if kind == "owner":
        return owner_map.get(value, value)
    if kind == "team":
        return team_name_map.get(value, value)
    return value


def pseudonymize_result(func_name: str, result, owner_map: dict, team_name_map: dict):
    name_fields = NAME_FIELDS.get(func_name, {})
    if not name_fields:
        return result

    if isinstance(result, dict):
        result = dict(result)
        for field, kind in name_fields.items():
            if field in result:
                result[field] = pseudonymize_value(
                    result[field], kind, owner_map, team_name_map
                )
        return result

    # DataFrame case
    for field, kind in name_fields.items():
        if field in result.columns:
            mapping = owner_map if kind == "owner" else team_name_map
            result[field] = result[field].map(mapping).fillna(result[field])
    return result


def capture_season(func_name: str, func, season: int, owner_map: dict, team_name_map: dict) -> dict:
    try:
        result = func(season)
    except SeasonNotReadyError as e:
        return {"error": str(e), "error_type": "SeasonNotReadyError"}
    except Exception as e:  # noqa: BLE001 — intentional: one bad season must not abort the whole capture
        return {"error": str(e), "error_type": type(e).__name__}

    result = pseudonymize_result(func_name, result, owner_map, team_name_map)

    if hasattr(result, "to_dict"):
        return {"records": result.to_dict(orient="records")}
    return result


def main() -> None:
    print(f"Capturing regression baseline from {DEFAULT_DB_PATH}")
    owner_map, team_name_map = build_pseudonym_maps(DEFAULT_DB_PATH)
    print(f"Pseudonymized {len(owner_map)} owners, {len(team_name_map)} team names.")

    baseline = {}
    for season in ALL_SEASONS:
        baseline[str(season)] = {}
        for func_name, func in FUNCTIONS.items():
            baseline[str(season)][func_name] = capture_season(
                func_name, func, season, owner_map, team_name_map
            )
        print(f"  season {season}: captured")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(baseline, f, indent=2, sort_keys=True)

    print(f"\nWrote baseline for {len(ALL_SEASONS)} seasons to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
