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


def log_question(
    tool_used: str | None,
    analysis_used: str | None,
    tokens_input: int,
    tokens_output: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """
    Log one question's usage as a row in chat_log.
    Best effort — never raises; failures are logged as warnings only,
    since usage tracking must never block the chatbot response.
    """
    try:
        conn = get_ops_connection()
        conn.execute(
            """
            INSERT INTO chat_log (
                tool_used, analysis_used,
                tokens_input, tokens_output,
                cache_write_tokens, cache_read_tokens
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                tool_used,
                analysis_used,
                tokens_input,
                tokens_output,
                cache_write_tokens,
                cache_read_tokens,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Turso write failed: {e}")


def get_today_usage() -> tuple[int, int, int]:
    """
    Read today's aggregate usage from the `usage` view.
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


def get_usage_report() -> list[tuple]:
    """
    Fetch daily usage and estimated cost, most recent first.
    Unlike get_today_usage/log_question, errors are not swallowed here —
    this is invoked interactively via scripts/usage_report.py, where a
    raised exception is more useful than a silently empty report.
    """
    conn = get_ops_connection()
    rows = conn.execute(
        """
        SELECT
            date,
            question_count,
            tokens_input,
            tokens_output,
            cache_write_tokens,
            cache_read_tokens,
            est_cost_usd
        FROM usage
        ORDER BY date DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_question_cost_report() -> list[tuple]:
    """
    Fetch per-question usage and estimated cost, most recent first.
    Unlike get_today_usage/log_question, errors are not swallowed here —
    this is invoked interactively via scripts/usage_report.py, where a
    raised exception is more useful than a silently empty report.
    """
    conn = get_ops_connection()
    rows = conn.execute(
        """
        SELECT
            id,
            created_at,
            tool_used,
            analysis_used,
            tokens_input,
            tokens_output,
            cache_write_tokens,
            cache_read_tokens,
            est_cost_usd
        FROM question_cost
        ORDER BY created_at DESC
        """
    ).fetchall()
    conn.close()
    return rows


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
