# scripts/usage_report.py
"""
Print daily chatbot usage and estimated Claude API cost from the Turso ops DB.

Usage:
    poetry run python scripts/usage_report.py
"""

from leagueintel.reporting.turso_client import get_usage_report

rows = get_usage_report()

print(
    f"{'date':<12}{'questions':>10}{'in':>10}{'out':>10}"
    f"{'cache_wr':>10}{'cache_rd':>10}{'est_cost_usd':>14}"
)
for date, question_count, tokens_input, tokens_output, cache_write, cache_read, est_cost_usd in rows:
    print(
        f"{date:<12}{question_count:>10}{tokens_input:>10}{tokens_output:>10}"
        f"{cache_write:>10}{cache_read:>10}{est_cost_usd:>14}"
    )
