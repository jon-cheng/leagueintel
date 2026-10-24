# tests/scripts/test_capture_regression_baseline.py
import sqlite3

import pandas as pd
import pytest

from leagueintel.config import CURRENT_YEAR
from scripts.capture_regression_baseline import (
    BASELINE_SEASONS,
    build_pseudonym_maps,
    pseudonymize_result,
)


def _make_teams_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE teams (season INTEGER, team_id INTEGER, team_name TEXT, owner_name TEXT)"
    )
    conn.executemany("INSERT INTO teams VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


@pytest.fixture
def teams_db(tmp_path):
    path = tmp_path / "teams.db"
    _make_teams_db(
        path,
        [
            (2023, 4, "Alpha", "Owner A"),
            (2023, 7, "Bravo", "Owner B"),
            (2026, 4, "Charlie", "Owner A"),
            (2026, 7, "Delta", "Owner B"),
        ],
    )
    return path


def test_team_rename_does_not_change_any_label(teams_db):
    """
    Protects against labels derived from a team's NAME. Renaming a team
    in-season (here 2026 team 4: Charlie -> Aardvark, which also changes
    its alphabetical position) used to shift other teams' labels across
    every season and break the whole baseline.
    """
    _, before = build_pseudonym_maps(teams_db)

    conn = sqlite3.connect(teams_db)
    conn.execute("UPDATE teams SET team_name = 'Aardvark' WHERE season = 2026 AND team_id = 4")
    conn.commit()
    conn.close()
    _, after = build_pseudonym_maps(teams_db)

    assert after[(2026, "Aardvark")] == before[(2026, "Charlie")]
    unchanged = {k: v for k, v in before.items() if k != (2026, "Charlie")}
    assert {k: after[k] for k in unchanged} == unchanged


def test_team_label_follows_team_id_across_seasons(teams_db):
    """
    Protects the identity the label is meant to carry: team 4 named
    differently in 2023 and 2026 is still the same team.
    """
    _, team_name_map = build_pseudonym_maps(teams_db)

    assert team_name_map[(2023, "Alpha")] == "team_4"
    assert team_name_map[(2026, "Charlie")] == "team_4"


def test_same_name_in_different_seasons_keeps_each_team_id(tmp_path):
    """
    Protects against a lookup keyed on name alone: if team 4 used "Alpha"
    in 2023 and team 7 used "Alpha" in 2025, each must keep its own label.
    """
    path = tmp_path / "teams.db"
    _make_teams_db(
        path,
        [
            (2023, 4, "Alpha", "Owner A"),
            (2025, 7, "Alpha", "Owner B"),
        ],
    )
    _, team_name_map = build_pseudonym_maps(path)

    assert team_name_map[(2023, "Alpha")] == "team_4"
    assert team_name_map[(2025, "Alpha")] == "team_7"


def test_owner_rename_does_not_change_any_label(teams_db):
    """Same protection as the team rename test, for manager labels."""
    before, _ = build_pseudonym_maps(teams_db)

    conn = sqlite3.connect(teams_db)
    conn.execute("UPDATE teams SET owner_name = 'Aaron A' WHERE season = 2026 AND team_id = 4")
    conn.commit()
    conn.close()
    after, _ = build_pseudonym_maps(teams_db)

    assert after[(2026, "Aaron A")] == "manager_4"
    assert after[(2023, "Owner B")] == before[(2023, "Owner B")] == "manager_7"


def test_pseudonymize_result_uses_the_given_season(teams_db):
    """
    Protects the season plumbing: the same real name must resolve through
    the season being compared, not some other season's mapping.
    """
    owner_map, team_name_map = build_pseudonym_maps(teams_db)
    result = pd.DataFrame({"owner_name": ["Owner A"], "team_name": ["Charlie"]})

    out = pseudonymize_result("get_waiver_scores", result, 2026, owner_map, team_name_map)

    assert out.to_dict(orient="records") == [{"owner_name": "manager_4", "team_name": "team_4"}]


def test_pseudonymize_result_handles_dict_results(teams_db):
    """Protects the dict-shaped results (medal standings etc.), not just DataFrames."""
    owner_map, team_name_map = build_pseudonym_maps(teams_db)

    out = pseudonymize_result(
        "get_medal_standings",
        {"first": "Owner B", "second": "Owner A", "third": None},
        2023,
        owner_map,
        team_name_map,
    )

    assert out == {"first": "manager_7", "second": "manager_4", "third": None}


def test_every_name_column_in_every_result_gets_pseudonymized(teams_db):
    """
    Protects against real names leaking into the committed (public)
    fixture. get_standings returned a team_name column that NAME_FIELDS
    didn't list, so real team names were written verbatim. Any result
    column that carries a real name must be listed.
    """
    owner_map, team_name_map = build_pseudonym_maps(teams_db)
    standings = pd.DataFrame({"manager": ["Owner A"], "team_name": ["Alpha"]})

    out = pseudonymize_result("get_standings", standings, 2023, owner_map, team_name_map)

    assert out.to_dict(orient="records") == [{"manager": "manager_4", "team_name": "team_4"}]


def test_baseline_excludes_the_live_season():
    """
    Protects the baseline from the live season: its standings change every
    week as games are played, which made the regression test fail on every
    refresh regardless of code changes.
    """
    assert CURRENT_YEAR not in BASELINE_SEASONS
    assert CURRENT_YEAR - 1 in BASELINE_SEASONS  # last completed season is still covered
