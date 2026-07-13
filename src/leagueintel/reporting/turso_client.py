# src/leagueintel/reporting/turso_client.py
"""
Turso (hosted SQLite) client for chatbot usage tracking.
Persists across Streamlit Cloud cold starts, unlike /tmp SQLite.
"""

from datetime import date
import os
from loguru import logger


def get_ops_connection():
    """
    Connect to leagueintel-ops Turso DB.
    Lazy — called at use time not import time.
    Same pattern as _get_client() for Anthropic.
    """
    import libsql_experimental as libsql

    return libsql.connect(
        database=os.getenv("TURSO_OPS_URL"),
        auth_token=os.getenv("TURSO_OPS_TOKEN"),
    )


def get_today_usage() -> tuple[int, int, int]:
    """
    Read today's usage from Turso usage table.
    Returns (tokens_input, tokens_output, question_count).
    Returns (0, 0, 0) on any error — never blocks the chatbot.
    """
    try:
        conn = get_ops_connection()
        row = conn.execute(
            "SELECT tokens_input, tokens_output, question_count "
            "FROM usage WHERE date = ?",
            (str(date.today()),),
        ).fetchone()
        conn.close()
        return row if row else (0, 0, 0)
    except Exception as e:
        logger.warning(f"Turso read failed: {e}")
        return (0, 0, 0)


def record_usage(tokens_input: int, tokens_output: int) -> None:
    """
    Upsert today's token usage into Turso.
    Best effort — never blocks the chatbot response.
    Uses same INSERT OR REPLACE pattern as leagueintel.db writes.
    """
    try:
        conn = get_ops_connection()
        conn.execute(
            """
            INSERT INTO usage (date, tokens_input, tokens_output, question_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(date) DO UPDATE SET
                tokens_input   = tokens_input   + excluded.tokens_input,
                tokens_output  = tokens_output  + excluded.tokens_output,
                question_count = question_count + 1
            """,
            (str(date.today()), tokens_input, tokens_output),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Turso write failed: {e}")


def check_daily_budget() -> tuple[bool, int]:
    """
    Check whether today's token budget has been exceeded.
    Returns (within_budget, tokens_used_today).
    Reads limit from CHATBOT_DAILY_TOKEN_LIMIT env var via config.
    """
    from leagueintel.config import CHATBOT_DAILY_TOKEN_LIMIT

    tokens_in, tokens_out, _ = get_today_usage()
    tokens_used = tokens_in + tokens_out
    return tokens_used < CHATBOT_DAILY_TOKEN_LIMIT, tokens_used
