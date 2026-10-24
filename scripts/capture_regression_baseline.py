# scripts/capture_regression_baseline.py
"""
Captures a regression baseline: for every completed season (BASELINE_SEASONS), calls the
six core analytics entry points against the REAL leagueintel.db and
serializes the results to tests/fixtures/regression_baseline.json.

This baseline exists so an upcoming refactor (making standings/draft/waiver
analytics driven by ESPN league settings instead of hardcoded assumptions)
can be checked against real historical output, not just synthetic fixtures.
See tests/analytics/test_regression_baseline.py for the test that diffs
against this file.

owner_name/team_name are pseudonymized before writing (manager_{team_id},
team_{team_id}) so real people's names never land in a committed fixture.
The mapping is rebuilt fresh each run from the teams table — nothing about
the real mapping itself is persisted anywhere.

Usage:
    poetry run python scripts/capture_regression_baseline.py
"""

import json
import sqlite3
from pathlib import Path

from leagueintel.analytics.availability import SeasonNotReadyError
from leagueintel.analytics.consolation import (
    get_consolation_ladder_winner,
    get_medal_standings,
    get_toilet_bowl_loser,
)
from leagueintel.analytics.draft import get_draft_roi
from leagueintel.analytics.standings import get_standings
from leagueintel.analytics.waiver import get_waiver_scores
from leagueintel.config import ALL_SEASONS, CURRENT_YEAR, DEFAULT_DB_PATH, REPO_ROOT

OUTPUT_PATH = REPO_ROOT / "tests" / "fixtures" / "regression_baseline.json"

# Completed seasons only: the live season's results change every week as
# games are played, so a baseline of it would fail on every refresh for
# reasons that have nothing to do with code changes.
BASELINE_SEASONS = [season for season in ALL_SEASONS if season < CURRENT_YEAR]

# fields known to carry real owner/team names, per function — see
# GENERALIZATION_PLAN.md step 1 for how this was enumerated
NAME_FIELDS = {
    "get_standings": {"manager": "owner", "team_name": "team"},
    "get_medal_standings": {"first": "owner", "second": "owner", "third": "owner"},
    "get_consolation_ladder_winner": {"winner": "owner", "opponent": "owner"},
    "get_toilet_bowl_loser": {"last_place": "owner", "opponent": "owner"},
    "get_draft_roi": {"owner_name": "owner"},
    "get_waiver_scores": {"owner_name": "owner", "team_name": "team"},
}

FUNCTIONS = {
    "get_standings": get_standings,
    "get_medal_standings": get_medal_standings,
    "get_consolation_ladder_winner": get_consolation_ladder_winner,
    "get_toilet_bowl_loser": get_toilet_bowl_loser,
    "get_draft_roi": get_draft_roi,
    "get_waiver_scores": get_waiver_scores,
}


def build_pseudonym_maps(db_path: Path) -> tuple[dict, dict]:
    """
    Build (season, owner_name) -> "manager_{team_id}" and
    (season, team_name) -> "team_{team_id}" maps.

    Labels come from team_id alone, never from a name's position in some
    ordering — so a team or owner renamed (even mid-season) keeps its
    label, and no other team's label moves. The analytics results only
    carry names, not team_id, so names are still the lookup key; keying
    by (season, name) keeps that lookup unambiguous, since names are
    unique within a season but can be reused across seasons.

    A team_id can change hands across seasons, so manager_N may refer to
    different people in different seasons. That's fine here: the baseline
    is compared one season at a time.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT season, team_id, team_name, owner_name FROM teams").fetchall()
    conn.close()

    owner_map = {(season, owner): f"manager_{team_id}" for season, team_id, _, owner in rows}
    team_name_map = {(season, team): f"team_{team_id}" for season, team_id, team, _ in rows}
    return owner_map, team_name_map


def pseudonymize_value(value, kind: str, season: int, owner_map: dict, team_name_map: dict):
    if kind == "owner":
        return owner_map.get((season, value), value)
    if kind == "team":
        return team_name_map.get((season, value), value)
    return value


def pseudonymize_result(
    func_name: str, result, season: int, owner_map: dict, team_name_map: dict
):
    name_fields = NAME_FIELDS.get(func_name, {})
    if not name_fields:
        return result

    if isinstance(result, dict):
        result = dict(result)
        for field, kind in name_fields.items():
            if field in result:
                result[field] = pseudonymize_value(
                    result[field], kind, season, owner_map, team_name_map
                )
        return result

    # DataFrame case
    for field, kind in name_fields.items():
        if field in result.columns:
            result[field] = result[field].map(
                lambda v: pseudonymize_value(v, kind, season, owner_map, team_name_map)
            )
    return result


def capture_season(func_name: str, func, season: int, owner_map: dict, team_name_map: dict) -> dict:
    try:
        result = func(season)
    except SeasonNotReadyError as e:
        return {"error": str(e), "error_type": "SeasonNotReadyError"}
    except Exception as e:  # noqa: BLE001 — intentional: one bad season must not abort the whole capture
        return {"error": str(e), "error_type": type(e).__name__}

    result = pseudonymize_result(func_name, result, season, owner_map, team_name_map)

    if hasattr(result, "to_dict"):
        return {"records": result.to_dict(orient="records")}
    return result


def main() -> None:
    print(f"Capturing regression baseline from {DEFAULT_DB_PATH}")
    owner_map, team_name_map = build_pseudonym_maps(DEFAULT_DB_PATH)
    print(f"Pseudonymized {len(owner_map)} owners, {len(team_name_map)} team names.")

    baseline = {}
    for season in BASELINE_SEASONS:
        baseline[str(season)] = {}
        for func_name, func in FUNCTIONS.items():
            baseline[str(season)][func_name] = capture_season(
                func_name, func, season, owner_map, team_name_map
            )
        print(f"  season {season}: captured")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(baseline, f, indent=2, sort_keys=True)

    print(f"\nWrote baseline for {len(BASELINE_SEASONS)} seasons to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
