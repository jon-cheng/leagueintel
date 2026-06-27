"""
ESPN API ingestion layer.
Fetches raw transaction data and saves as JSON.
"""

import os
import json
import time
import requests
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv, find_dotenv

REPO_ROOT = Path(find_dotenv()).parent
load_dotenv(REPO_ROOT / ".env")  # load .env FIRST

LEAGUE_ID = os.getenv("LEAGUE_ID")  # now reads correctly
ESPN_S2 = os.getenv("ESPN_S2")
SWID = os.getenv("SWID")

BASE_URL = (
    "https://lm-api-reads.fantasy.espn.com"
    "/apis/v3/games/ffl/seasons/{year}"
    "/segments/0/leagues/{league_id}"
)

ALL_SEASONS = [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]
DEFAULT_MAX_WEEK = 17


def _get_weeks(max_week: int = DEFAULT_MAX_WEEK) -> list[int]:
    return list(range(1, max_week + 1))


DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "raw"


def _fetch_week(year: int, week: int) -> dict:
    """Fetch raw transaction data from ESPN API for a given year and week."""
    url = BASE_URL.format(year=year, league_id=LEAGUE_ID)
    params = {"scoringPeriodId": week, "view": "mTransactions2"}
    cookies = {"espn_s2": ESPN_S2, "SWID": SWID}
    response = requests.get(url, params=params, cookies=cookies, timeout=10)
    response.raise_for_status()
    return response.json()


def _save_raw(data: dict, year: int, week: int, output_dir: str) -> str:
    """Save raw JSON response to disk or S3."""
    filename = f"week{week:02d}.json"
    content = json.dumps(data, indent=2)

    if str(output_dir).startswith("s3://"):
        raise NotImplementedError("S3 support coming soon")

    path = Path(output_dir) / str(year) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)


def _summarize(transactions: list) -> tuple[int, int, int]:
    """Return counts of executed waivers, failed waivers, and draft picks."""
    waiver_executed = sum(
        1 for t in transactions if t["type"] == "WAIVER" and t["status"] == "EXECUTED"
    )
    waiver_failed = sum(
        1
        for t in transactions
        if t["type"] == "WAIVER" and t["status"].startswith("FAILED")
    )
    draft = sum(1 for t in transactions if t["type"] == "DRAFT")
    return waiver_executed, waiver_failed, draft


def fetch_transactions_all(
    year: int = None,
    week: int = None,
    max_week: int = DEFAULT_MAX_WEEK,
    output_dir: str = None,
) -> None:
    """
    Fetch ESPN transaction data for given year/week and save as raw JSON.

    Args:
        year: Season year. If None, fetches all seasons.
        week: Specific week number 1-max_week. If omitted, fetches all weeks.
        max_week: Maximum week to fetch. Defaults to 17.
        output_dir: Output directory. Defaults to data/raw/.
    """
    if not all([LEAGUE_ID, ESPN_S2, SWID]):
        logger.error(
            "Missing credentials. Ensure LEAGUE_ID, ESPN_S2, SWID "
            "are set in your .env file."
        )
        return

    years = [year] if year else ALL_SEASONS
    weeks = [week] if week else _get_weeks(max_week)
    output_dir = output_dir or DEFAULT_OUTPUT_DIR

    logger.info(
        f"Fetching {len(years)} season(s) × {len(weeks)} week(s) "
        f"= {len(years) * len(weeks)} requests"
    )
    logger.info(f"Output directory: {output_dir}")

    success, errors = 0, 0

    for y in years:
        logger.info(f"=== Season {y} ===")
        for w in weeks:
            try:
                data = _fetch_week(y, w)
                path = _save_raw(data, y, w, output_dir)

                transactions = data.get("transactions", [])
                waiver_executed, waiver_failed, draft = _summarize(transactions)

                logger.info(
                    f"week {w:02d}: {len(transactions)} total | "
                    f"{waiver_executed} waiver wins | "
                    f"{waiver_failed} waiver losses | "
                    f"{draft} draft | "
                    f"saved → {Path(path).name}"
                )
                success += 1
                time.sleep(0.5)

            except requests.HTTPError as e:
                logger.warning(f"week {w:02d}: HTTP ERROR {e.response.status_code}")
                errors += 1
            except requests.Timeout:
                logger.warning(f"week {w:02d}: TIMEOUT")
                errors += 1
            except NotImplementedError as e:
                logger.error(f"week {w:02d}: {e}")
                errors += 1
            except Exception as e:
                logger.error(f"week {w:02d}: ERROR — {e}")
                errors += 1

    logger.info(f"Done. {success} succeeded, {errors} failed.")

    if errors > 0:
        logger.warning(f"{errors} week(s) failed — check logs above")
        raise SystemExit(1)
