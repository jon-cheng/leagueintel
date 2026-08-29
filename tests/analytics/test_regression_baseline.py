# tests/analytics/test_regression_baseline.py
"""
Regression safety net for the upcoming settings-driven-analytics refactor
(GENERALIZATION_PLAN.md step 4+): reruns the six core analytics entry
points against the REAL leagueintel.db and diffs the result against the
committed baseline in tests/fixtures/regression_baseline.json.

The baseline was captured (and must be re-captured after any INTENTIONAL
behavior change) via scripts/capture_regression_baseline.py. This test
does not regenerate it — it only compares.

Requires a real leagueintel.db at DEFAULT_DB_PATH, so it's excluded from
the default CI run and must be run explicitly:
    poetry run pytest -m regression -v
"""

import json
import math

import pandas as pd
import pytest

from leagueintel.config import ALL_SEASONS, DEFAULT_DB_PATH, REPO_ROOT
from leagueintel.analytics.availability import SeasonNotReadyError
from leagueintel.analytics.standings import get_standings
from leagueintel.analytics.consolation import (
    get_medal_standings,
    get_arbys_winner,
    get_toilet_bowl_loser,
)
from leagueintel.analytics.draft import get_draft_roi
from leagueintel.analytics.waiver import get_waiver_scores

from scripts.capture_regression_baseline import (
    build_pseudonym_maps,
    pseudonymize_result,
)

BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "regression_baseline.json"

FUNCTIONS = {
    "get_standings": get_standings,
    "get_medal_standings": get_medal_standings,
    "get_arbys_winner": get_arbys_winner,
    "get_toilet_bowl_loser": get_toilet_bowl_loser,
    "get_draft_roi": get_draft_roi,
    "get_waiver_scores": get_waiver_scores,
}

FLOAT_REL_TOL = 1e-6


@pytest.fixture(scope="module")
def baseline():
    if not BASELINE_PATH.exists():
        pytest.skip(f"No baseline file at {BASELINE_PATH} — run scripts/capture_regression_baseline.py first")
    with open(BASELINE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def pseudonym_maps():
    if not DEFAULT_DB_PATH.exists():
        pytest.skip(f"No real database at {DEFAULT_DB_PATH} — regression tests need the real leagueintel.db")
    return build_pseudonym_maps(DEFAULT_DB_PATH)


def _rerun(func_name, func, season, owner_map, team_name_map):
    try:
        result = func(season)
    except SeasonNotReadyError as e:
        return {"error": str(e), "error_type": "SeasonNotReadyError"}
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}

    result = pseudonymize_result(func_name, result, owner_map, team_name_map)
    if hasattr(result, "to_dict"):
        return {"records": result.to_dict(orient="records")}
    return result


def _assert_scalar_equal(actual, expected, path):
    if isinstance(actual, float) or isinstance(expected, float):
        assert math.isclose(actual, expected, rel_tol=FLOAT_REL_TOL), (
            f"{path}: expected {expected!r}, got {actual!r}"
        )
    else:
        assert actual == expected, f"{path}: expected {expected!r}, got {actual!r}"


def _assert_dict_equal(actual: dict, expected: dict, path: str):
    assert actual.keys() == expected.keys(), (
        f"{path}: key mismatch — expected {sorted(expected.keys())}, got {sorted(actual.keys())}"
    )
    for key in expected:
        _assert_scalar_equal(actual[key], expected[key], f"{path}.{key}")


def _assert_records_equal(actual_records: list, expected_records: list, path: str):
    actual_df = pd.DataFrame(actual_records).reset_index(drop=True)
    expected_df = pd.DataFrame(expected_records).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(
            actual_df, expected_df, check_exact=False, rtol=FLOAT_REL_TOL, check_like=True
        )
    except AssertionError as e:
        raise AssertionError(f"{path}: DataFrame mismatch\n{e}") from e


@pytest.mark.regression
@pytest.mark.parametrize("season", ALL_SEASONS)
@pytest.mark.parametrize("func_name", list(FUNCTIONS.keys()))
def test_matches_baseline(season, func_name, baseline, pseudonym_maps):
    season_key = str(season)
    if season_key not in baseline or func_name not in baseline[season_key]:
        pytest.skip(f"No baseline captured for season={season}, func={func_name}")

    expected = baseline[season_key][func_name]
    owner_map, team_name_map = pseudonym_maps
    actual = _rerun(func_name, FUNCTIONS[func_name], season, owner_map, team_name_map)

    path = f"season={season} {func_name}"

    # a season that errored in the baseline but succeeds now (or vice
    # versa) is exactly the kind of behavior change this test exists to
    # catch — always a hard failure, regardless of tolerance settings
    assert ("error" in actual) == ("error" in expected), (
        f"{path}: error-state changed — baseline={expected.get('error_type', 'no error')}, "
        f"now={actual.get('error_type', 'no error')}"
    )
    if "error" in expected:
        assert actual["error_type"] == expected["error_type"], path
        return

    if "records" in expected:
        _assert_records_equal(actual["records"], expected["records"], path)
    else:
        _assert_dict_equal(actual, expected, path)
