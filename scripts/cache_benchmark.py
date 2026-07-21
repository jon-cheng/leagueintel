# scripts/cache_benchmark.py
"""
Benchmark chatbot cost with prompt caching on vs off.

Not a pytest test — a standalone script meant to be run twice manually,
once per mode, so the two printed tables can be compared by hand:

    ENABLE_PROMPT_CACHING=false poetry run python scripts/cache_benchmark.py
    ENABLE_PROMPT_CACHING=true  poetry run python scripts/cache_benchmark.py
"""

from unittest.mock import patch

from leagueintel.config import ENABLE_PROMPT_CACHING
import leagueintel.reporting.chatbot as chatbot

QUESTIONS = [
    "What was the highest single-week score in 2022?",
    "How many trades happened in 2021?",
    "Which manager has the most championship game appearances?",
]

# same per-token pricing as the `usage` view in Turso — kept in sync manually
PRICE_PER_MTOK = {
    "input": 3.00,
    "cache_write": 3.75,
    "cache_read": 0.30,
    "output": 15.0,
}


def _est_cost(totals: dict) -> float:
    return round(
        (
            totals["input"] * PRICE_PER_MTOK["input"]
            + totals["cache_write"] * PRICE_PER_MTOK["cache_write"]
            + totals["cache_read"] * PRICE_PER_MTOK["cache_read"]
            + totals["output"] * PRICE_PER_MTOK["output"]
        )
        / 1_000_000,
        4,
    )


def run_benchmark() -> dict:
    totals = {"questions": 0, "input": 0, "cache_write": 0, "cache_read": 0, "output": 0}

    def _capture_usage(
        tool_used,
        analysis_used,
        tokens_input,
        tokens_output,
        cache_write_tokens=0,
        cache_read_tokens=0,
    ):
        totals["questions"] += 1
        totals["input"] += tokens_input
        totals["output"] += tokens_output
        totals["cache_write"] += cache_write_tokens
        totals["cache_read"] += cache_read_tokens

    with patch.object(chatbot, "log_question", side_effect=_capture_usage):
        for question in QUESTIONS:
            chatbot.ask(question)

    return totals


if __name__ == "__main__":
    totals = run_benchmark()
    mode = "caching=on" if ENABLE_PROMPT_CACHING else "caching=off"

    print(f"\n{'Mode':<14}{'Questions':>10}{'Input tok':>12}"
          f"{'Cache write':>13}{'Cache read':>12}{'Output tok':>12}{'Est. cost':>12}")
    print(
        f"{mode:<14}{totals['questions']:>10}{totals['input']:>12}"
        f"{totals['cache_write']:>13}{totals['cache_read']:>12}"
        f"{totals['output']:>12}{'$' + str(_est_cost(totals)):>12}"
    )
