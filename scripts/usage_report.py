# scripts/usage_report.py
"""
Print daily chatbot usage and estimated Claude API cost from the Turso ops DB.

Usage:
    poetry run python scripts/usage_report.py
"""

from leagueintel.reporting.turso_client import get_usage_report

rows = get_usage_report()

print(f"{'date':<12}{'questions':>10}{'tokens':>12}{'est_cost_usd':>14}")
for date, question_count, total_tokens, est_cost_usd in rows:
    print(f"{date:<12}{question_count:>10}{total_tokens:>12}{est_cost_usd:>14}")
