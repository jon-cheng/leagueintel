# tests/reporting/test_chatbot_throttling.py
"""
Tests for chatbot daily token budget throttling.

Usage tracking now lives in Turso (see test_turso_client.py for the
storage-layer tests) — these tests only cover chatbot.py's own logic:
that ask() checks the budget before calling the Anthropic API, and
short-circuits with a friendly message instead of calling it when the
budget is exceeded. check_daily_budget/record_usage are patched at the
name they're imported under in chatbot.py, not in turso_client, since
that's the name ask() actually calls.
"""

from unittest.mock import patch, MagicMock

import leagueintel.reporting.chatbot as chatbot_module


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
    """ask() calls record_usage with the response's token counts once it has an answer."""
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_text_block = MagicMock()
    mock_text_block.text = "Some answer"
    mock_response.content = [mock_text_block]
    mock_response.usage.input_tokens = 1234
    mock_response.usage.output_tokens = 567

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with (
        patch.object(chatbot_module, "check_daily_budget", return_value=(True, 0)),
        patch.object(chatbot_module, "_get_client", return_value=mock_client),
        patch.object(chatbot_module, "record_usage") as mock_record_usage,
    ):
        text, fig = chatbot_module.ask("Who won the league in 2023?")

    assert text == "Some answer"
    mock_record_usage.assert_called_once_with(1234, 567)


def test_ask_records_usage_across_every_tool_use_round_trip():
    """
    A question that takes two tool calls before answering makes three
    separate messages.create() calls. record_usage must be called once,
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

    tool_response_1 = MagicMock()
    tool_response_1.stop_reason = "tool_use"
    tool_response_1.content = [tool_block]
    tool_response_1.usage.input_tokens = 1000
    tool_response_1.usage.output_tokens = 100

    tool_response_2 = MagicMock()
    tool_response_2.stop_reason = "tool_use"
    tool_response_2.content = [tool_block]
    tool_response_2.usage.input_tokens = 2000
    tool_response_2.usage.output_tokens = 200

    final_text_block = MagicMock()
    final_text_block.text = "Final answer"
    final_response = MagicMock()
    final_response.stop_reason = "end_turn"
    final_response.content = [final_text_block]
    final_response.usage.input_tokens = 3000
    final_response.usage.output_tokens = 300

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
        patch.object(chatbot_module, "record_usage") as mock_record_usage,
    ):
        text, fig = chatbot_module.ask("A question needing two tool calls")

    assert text == "Final answer"
    mock_record_usage.assert_called_once_with(1000 + 2000 + 3000, 100 + 200 + 300)
