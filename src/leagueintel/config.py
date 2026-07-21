"""
Single source of truth for constants, paths, and environment variables.
"""

import os
from pathlib import Path
from datetime import date
from dotenv import load_dotenv, find_dotenv
import streamlit as st

REPO_ROOT = Path(find_dotenv()).parent
load_dotenv(REPO_ROOT / ".env")


def _get_env(key: str, default: str = None) -> str:
    """Read from env var first, then st.secrets, then default."""
    val = os.getenv(key)
    if val:
        return val.strip()
    try:
        val = st.secrets.get(key, default)
        return val.strip() if val else val
    except Exception:
        return default


ANTHROPIC_API_KEY = _get_env("ANTHROPIC_API_KEY")

# ESPN credentials
LEAGUE_ID = _get_env("LEAGUE_ID")
ESPN_S2 = _get_env("ESPN_S2")
SWID = _get_env("SWID")

# seasons
CURRENT_YEAR = date.today().year
ALL_SEASONS = list(range(2019, CURRENT_YEAR + 1))

# paths
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "raw"

# DB_PATH env var allows cloud deployments to override the local path
# e.g. DB_PATH=/tmp/leagueintel.db on Streamlit Community Cloud
# falls back to local repo path for development
DEFAULT_DB_PATH = Path(os.getenv("DB_PATH", str(REPO_ROOT / "leagueintel.db")))

# S3 config for cloud deployments
S3_BUCKET = os.getenv("S3_BUCKET", "leagueintel-data")
S3_KEY = os.getenv("S3_KEY", "leagueintel.db")

# usage tracking DB — kept separate from leagueintel.db so the weekly
# data refresh (which overwrites leagueintel.db from S3) never clobbers it
USAGE_DB_PATH = Path(os.getenv("USAGE_DB_PATH", str(REPO_ROOT / "leagueintel_usage.db")))
S3_USAGE_KEY = os.getenv("S3_USAGE_KEY", "leagueintel_usage.db")

# ESPN API
DEFAULT_MAX_WEEK = 17
BASE_URL = (
    "https://lm-api-reads.fantasy.espn.com"
    "/apis/v3/games/ffl/seasons/{year}"
    "/segments/0/leagues/{league_id}"
)

# Threshold games played for consideration in draft, waiver analyses
MIN_WEEKS = 8

# Draft ROI and Best Waiver need a full season's worth of weeks to be
# meaningful — too few weeks of the live season means small sample sizes
# and noisy comparisons. Lock these two analyses out for the current
# season until this many weeks have been ingested.
LIVE_SEASON_ANALYSIS_MIN_WEEK = 12

# ── chatbot token budget ──────────────────────────────────────────────────────
# Daily token limit across all users — protects against runaway API costs.
# Adjust here to tune throttling without touching chatbot code.
#
# Rough guide (claude-sonnet-4-6 at ~1,600 tokens/question):
#   50,000  → ~30 questions/day  (conservative)
#   100,000 → ~60 questions/day  (recommended for private league)
#   200,000 → ~120 questions/day (generous)
#
# For the public demo deployment set this lower (e.g. 20,000).
CHATBOT_DAILY_TOKEN_LIMIT = int(os.getenv("CHATBOT_DAILY_TOKEN_LIMIT", "100000"))

# Turso (hosted SQLite) — leagueintel-ops DB, stores chatbot usage tracking
# persistently across Streamlit Cloud cold starts (/tmp does not survive them)
TURSO_OPS_URL = os.getenv("TURSO_OPS_URL")
TURSO_OPS_TOKEN = os.getenv("TURSO_OPS_TOKEN")

# Dev flag to A/B the chatbot with/without prompt caching, so the same
# golden question set can be run twice (see scripts/cache_benchmark.py)
# and the real before/after cost difference measured directly.
ENABLE_PROMPT_CACHING = os.getenv("ENABLE_PROMPT_CACHING", "true").lower() == "true"
