# tests/reporting/test_golden_questions.py
"""
Runs tests.golden_questions.GOLDEN_QUESTIONS through the real chatbot
question-answering path (leagueintel.reporting.chatbot.ask), against the
real Anthropic API and the real leagueintel.db.

These exist to catch prompt-layer regressions — the kind of bug the first
golden question's own note documents (LLM-generated SQL got winner/loser
attribution backwards). That only shows up by exercising the real model's
tool-choice, so unlike test_chatbot_throttling.py, the Anthropic client
itself is NOT mocked here — only log_question is patched, to capture
which tool/analysis the real model chose (tool_used/analysis_used),
since ask()'s return value doesn't expose that directly.

Costs real Anthropic API tokens per run — excluded from the default CI
run, run explicitly:
    poetry run pytest -m llm -v
"""

from unittest.mock import patch

import pytest

import leagueintel.reporting.chatbot as chatbot_module
from tests.golden_questions import GOLDEN_QUESTIONS


def _ask_and_capture_routing(question: str):
    """
    Calls the real ask() (real API, real tools/DB) and captures the
    tool_used/analysis_used kwargs log_question was called with, since
    ask()'s return value doesn't expose routing info itself.

    wraps=... so the mock still calls through to the real log_question —
    these tests make real, real-money API calls, so the real Turso usage
    write must still happen. A bare MagicMock() here would silently skip
    that write while still burning real tokens: cost without bookkeeping.
    """
    with patch.object(
        chatbot_module, "log_question", wraps=chatbot_module.log_question
    ) as mock_log_question:
        text, fig = chatbot_module.ask(question)

    assert mock_log_question.called, "ask() should log usage even on a normal answer"
    call_kwargs = mock_log_question.call_args.kwargs
    return text, call_kwargs["tool_used"], call_kwargs["analysis_used"]


@pytest.mark.llm
@pytest.mark.parametrize(
    "case", GOLDEN_QUESTIONS, ids=[c["question"] for c in GOLDEN_QUESTIONS]
)
def test_golden_question(case):
    text, tool_used, analysis_used = _ask_and_capture_routing(case["question"])
    ground_truth = case["ground_truth"]

    if "interpretation" in ground_truth:
        interpretation = ground_truth["interpretation"]
        if "run_analysis(analysis='medal_standings')" in interpretation:
            assert tool_used == "run_analysis", (
                f"expected run_analysis routing, got tool_used={tool_used!r} "
                f"(analysis_used={analysis_used!r}) for: {case['question']!r}"
            )
            assert analysis_used == "medal_standings"
        elif "query_db" in interpretation:
            assert tool_used == "query_db", (
                f"expected query_db routing, got tool_used={tool_used!r} "
                f"(analysis_used={analysis_used!r}) for: {case['question']!r}"
            )

    # facts are checked loosely against the free-text response — exact
    # wording isn't guaranteed, so this checks that the key identifying
    # values show up somewhere in the answer, not an exact match
    for key in (
        "winner_score",
        "loser_score",
        "season",
        "week",
    ):
        if key in ground_truth:
            assert str(ground_truth[key]) in text, (
                f"expected {key}={ground_truth[key]!r} to appear in response "
                f"for: {case['question']!r}\nfull response: {text}"
            )
