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
    {
        "question": "who finished in first place in the 2024 season?",
        "note": "'first place' is ambiguous: the regular-season standings "
        "leader (team_id 8, best record/points_for) is a DIFFERENT "
        "team than the actual playoff champion (team_id 7, won the "
        "championship game). Default interpretation should be the "
        "playoff champion, via run_analysis(analysis='medal_standings'). "
        "Only fall back to regular-season standings (query_db) if the "
        "user explicitly says 'regular season'. Verified 6 of 7 seasons "
        "(2019-2024) have a different regular-season leader vs. playoff "
        "champion — this is the common case, not an edge case.",
        "ground_truth": {
            "season": 2024,
            "first_place_team_id": 7,
            "interpretation": "playoff champion, via "
            "run_analysis(analysis='medal_standings')",
            "regular_season_leader_team_id": 8,
            "regular_season_leader_note": "best record, but lost in "
            "playoffs — NOT first place",
        },
    },
    {
        "question": "who had the best regular season record in 2024?",
        "note": "Explicit 'regular season' phrasing should route to "
        "query_db against get_standings-equivalent logic, not "
        "run_analysis(analysis='medal_standings').",
        "ground_truth": {
            "season": 2024,
            "regular_season_leader_team_id": 8,
            "interpretation": "regular season standings, via query_db",
        },
    },
]
