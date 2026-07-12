"""
Gates week-sensitive analyses (Draft ROI, Best Waiver) during a live season.

Kept separate from the DB query that supplies max_ingested_week so the
gating rule itself — a pure function of two ints — can be unit tested
without a database fixture.
"""

from leagueintel.config import CURRENT_YEAR, LIVE_SEASON_ANALYSIS_MIN_WEEK


class SeasonNotReadyError(Exception):
    """Raised when the current season hasn't reached the minimum week
    threshold required for a week-sensitive analysis."""


def check_season_ready(season: int, max_ingested_week: int) -> None:
    """
    Raise SeasonNotReadyError if `season` is the live season and hasn't
    reached LIVE_SEASON_ANALYSIS_MIN_WEEK yet. Past seasons are always ready.
    """
    if season < CURRENT_YEAR:
        return
    if max_ingested_week < LIVE_SEASON_ANALYSIS_MIN_WEEK:
        raise SeasonNotReadyError(
            f"Analysis will be available by Week {LIVE_SEASON_ANALYSIS_MIN_WEEK} "
            "to allow for sufficient data."
        )


def get_default_season(max_ingested_week: int) -> int:
    """
    Return the season that should be pre-selected in the season dropdown.

    Defaults to last season until the live season reaches
    LIVE_SEASON_ANALYSIS_MIN_WEEK, so a first-time visitor doesn't land
    on a near-empty in-progress season. Users can still pick the live
    season manually at any point via the dropdown.
    """
    if max_ingested_week >= LIVE_SEASON_ANALYSIS_MIN_WEEK:
        return CURRENT_YEAR
    return CURRENT_YEAR - 1
