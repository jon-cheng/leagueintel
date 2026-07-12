# tests/analytics/test_availability.py
import pytest
import leagueintel.analytics.availability as availability_module
from leagueintel.analytics.availability import (
    check_season_ready,
    get_default_season,
    SeasonNotReadyError,
)


@pytest.fixture(autouse=True)
def fixed_current_year():
    """Pin CURRENT_YEAR so these tests don't depend on the real calendar date."""
    original = availability_module.CURRENT_YEAR
    availability_module.CURRENT_YEAR = 2026
    yield
    availability_module.CURRENT_YEAR = original


def test_past_season_always_ready():
    """A completed season should never be gated, regardless of ingested weeks."""
    check_season_ready(season=2025, max_ingested_week=0)  # should not raise


def test_live_season_blocked_before_threshold():
    """
    Regression target: the live season must be locked out of Draft ROI /
    Best Waiver until enough weeks of data exist, otherwise small samples
    produce misleading rankings.
    """
    with pytest.raises(SeasonNotReadyError):
        check_season_ready(season=2026, max_ingested_week=5)


def test_live_season_ready_at_threshold():
    """Week 12 itself (the configured minimum) should be considered ready."""
    check_season_ready(season=2026, max_ingested_week=12)  # should not raise


def test_live_season_ready_after_threshold():
    check_season_ready(season=2026, max_ingested_week=15)  # should not raise


# ── get_default_season ────────────────────────────────────────────────────────


def test_default_season_falls_back_before_threshold():
    """
    Before Week 12, the dropdown should default to last season so a
    first-time visitor doesn't land on a near-empty in-progress season.
    """
    assert get_default_season(max_ingested_week=5) == 2025


def test_default_season_switches_at_threshold():
    assert get_default_season(max_ingested_week=12) == 2026


def test_default_season_switches_after_threshold():
    assert get_default_season(max_ingested_week=17) == 2026
