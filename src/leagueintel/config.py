"""
Single source of truth for constants, paths, and environment variables.
"""

import os
from pathlib import Path
from datetime import date
from dotenv import load_dotenv, find_dotenv

REPO_ROOT = Path(find_dotenv()).parent
load_dotenv(REPO_ROOT / ".env")

# ESPN credentials
LEAGUE_ID = os.getenv("LEAGUE_ID")
ESPN_S2 = os.getenv("ESPN_S2")
SWID = os.getenv("SWID")

# seasons
CURRENT_YEAR = date.today().year
ALL_SEASONS = list(range(2019, CURRENT_YEAR))

# paths
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "raw"
DEFAULT_DB_PATH = REPO_ROOT / "leagueintel.db"

# ESPN API
DEFAULT_MAX_WEEK = 17
BASE_URL = (
    "https://lm-api-reads.fantasy.espn.com"
    "/apis/v3/games/ffl/seasons/{year}"
    "/segments/0/leagues/{league_id}"
)

# Theshold games played for consideration in draft, waiver analyses
MIN_WEEKS = 8
