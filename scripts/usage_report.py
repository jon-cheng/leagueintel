# scripts/usage_report.py
"""
Print daily chatbot usage and estimated Claude API cost from the Turso ops DB,
followed by a per-question breakdown from the question_cost view.

Usage:
    poetry run python scripts/usage_report.py
"""

import leagueintel.config  # noqa: F401 -- triggers load_dotenv() so TURSO_OPS_* are set
from leagueintel.reporting.turso_client import get_usage_report, get_question_cost_report

daily_rows = get_usage_report()

print("Daily rollup (usage view)")
print(
    f"{'date':<12}{'questions':>10}{'in':>10}{'out':>10}"
    f"{'cache_wr':>10}{'cache_rd':>10}{'est_cost_usd':>14}"
)
for date, question_count, tokens_input, tokens_output, cache_write, cache_read, est_cost_usd in daily_rows:
    print(
        f"{date:<12}{question_count:>10}{tokens_input:>10}{tokens_output:>10}"
        f"{cache_write:>10}{cache_read:>10}{est_cost_usd:>14}"
    )

question_rows = get_question_cost_report()

print("\nPer-question detail (question_cost view)")
print(
    f"{'id':<6}{'created_at':<22}{'tool_used':<14}{'analysis_used':<16}"
    f"{'in':>8}{'out':>8}{'cache_wr':>10}{'cache_rd':>10}{'est_cost_usd':>14}"
)
for (
    q_id,
    created_at,
    tool_used,
    analysis_used,
    tokens_input,
    tokens_output,
    cache_write,
    cache_read,
    est_cost_usd,
) in question_rows:
    print(
        f"{q_id:<6}{created_at:<22}{(tool_used or ''):<14}{(analysis_used or ''):<16}"
        f"{tokens_input:>8}{tokens_output:>8}{cache_write:>10}{cache_read:>10}{est_cost_usd:>14}"
    )
