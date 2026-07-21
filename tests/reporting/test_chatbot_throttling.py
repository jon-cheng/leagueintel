# tests/reporting/test_chatbot_throttling.py
"""
Tests for chatbot daily token budget throttling.

Usage tracking now lives in Turso (see test_turso_client.py for the
storage-layer tests) — these tests only cover chatbot.py's own logic:
that ask() checks the budget before calling the Anthropic API, and
short-circuits with a friendly message instead of calling it when the
budget is exceeded. check_daily_budget/log_question are patched at the
name they're imported under in chatbot.py, not in turso_client, since
that's the name ask() actually calls.
"""

from unittest.mock import patch, MagicMock

import leagueintel.reporting.chatbot as chatbot_module


def _mock_response(stop_reason, content, input_tokens, output_tokens):
    """
    Build a MagicMock response that behaves like the real SDK object.
    getattr(u, "cache_creation_input_tokens", 0) needs an explicit 0 here —
    a bare MagicMock().usage.cache_creation_input_tokens would otherwise
    return a truthy MagicMock instead of a real int.
    """
    response = MagicMock()
    response.stop_reason = stop_reason
    response.content = content
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    response.usage.cache_creation_input_tokens = 0
    response.usage.cache_read_input_tokens = 0
    return response


def test_ask_blocked_when_over_budget():
    """ask() returns the budget message without calling the API when over limit."""
    mock_client = MagicMock()
    with (
        patch.object(chatbot_module, "check_daily_budget", return_value=(False, 110)),
        patch.object(chatbot_module, "_get_client", return_value=mock_client),
    ):
        text, fig = chatbot_module.ask("Who had the best waiver pickup in 2025?")

    # API should never have been called
    mock_client.messages.create.assert_not_called()

    # response should be the budget message
    assert "limit" in text.lower()
    assert fig is None


def test_ask_records_usage_after_successful_response():
    """ask() calls log_question with the response's token counts once it has an answer."""
    mock_text_block = MagicMock()
    mock_text_block.text = "Some answer"
    mock_response = _mock_response("end_turn", [mock_text_block], 1234, 567)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with (
        patch.object(chatbot_module, "check_daily_budget", return_value=(True, 0)),
        patch.object(chatbot_module, "_get_client", return_value=mock_client),
        patch.object(chatbot_module, "log_question") as mock_log_question,
    ):
        text, fig = chatbot_module.ask("Who won the league in 2023?")

    assert text == "Some answer"
    mock_log_question.assert_called_once_with(
        tool_used=None,
        analysis_used=None,
        tokens_input=1234,
        tokens_output=567,
        cache_write_tokens=0,
        cache_read_tokens=0,
    )


def test_ask_records_usage_across_every_tool_use_round_trip():
    """
    A question that takes two tool calls before answering makes three
    separate messages.create() calls. log_question must be called once,
    at the end, with tokens summed across all three — not just the
    tokens from the final call. Regression guard for a bug where only
    the last response's usage was recorded, silently under-counting
    (and under-throttling) any multi-tool-call question.
    """
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "query_db"
    tool_block.input = {"sql": "SELECT 1"}
    tool_block.id = "tool_1"

    tool_response_1 = _mock_response("tool_use", [tool_block], 1000, 100)
    tool_response_2 = _mock_response("tool_use", [tool_block], 2000, 200)

    final_text_block = MagicMock()
    final_text_block.text = "Final answer"
    final_response = _mock_response("end_turn", [final_text_block], 3000, 300)

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        tool_response_1,
        tool_response_2,
        final_response,
    ]

    with (
        patch.object(chatbot_module, "check_daily_budget", return_value=(True, 0)),
        patch.object(chatbot_module, "_get_client", return_value=mock_client),
        patch.object(chatbot_module, "query_db", return_value=("ok", None)),
        patch.object(chatbot_module, "log_question") as mock_log_question,
    ):
        text, fig = chatbot_module.ask("A question needing two tool calls")

    assert text == "Final answer"
    mock_log_question.assert_called_once_with(
        tool_used="query_db",
        analysis_used=None,
        tokens_input=1000 + 2000 + 3000,
        tokens_output=100 + 200 + 300,
        cache_write_tokens=0,
        cache_read_tokens=0,
    )
