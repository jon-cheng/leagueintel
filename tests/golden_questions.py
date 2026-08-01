"""
Golden question/answer pairs for manual or automated chatbot regression checks.

Each case documents a real question, why it matters, and the known-correct
answer to check the chatbot's response against. Not wired into pytest yet —
intended for manual verification when SCHEMA_DESCRIPTION or SQL-generation
prompting changes.
"""

GOLDEN_QUESTIONS = [
    {
        "question": "what was the biggest blowout in league history?",
        "note": "real bug found — LLM-generated SQL against the wide "
        "matchups table got the winner/score attribution "
        "backwards (attributed the wrong score to the wrong "
        "team). Fixed by adding matchups_long and steering "
        "ad-hoc SQL generation toward it.",
        "ground_truth": {
            "season": 2020,
            "week": 12,
            "winner_team_id": 5,
            "winner_score": 164.1,
            "loser_team_id": 12,
            "loser_score": 68.3,
        },
    },
]
