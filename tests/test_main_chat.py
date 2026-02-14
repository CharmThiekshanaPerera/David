from __future__ import annotations

from agent.main import parse_chat_command


def test_parse_chat_command_exit():
    assert parse_chat_command("bye") == ("exit", "")
    assert parse_chat_command("  EXIT  ") == ("exit", "")


def test_parse_chat_command_help():
    assert parse_chat_command("/help") == ("help", "")


def test_parse_chat_command_modes():
    assert parse_chat_command("/goal build app") == ("goal", "build app")
    assert parse_chat_command("/ask who are you?") == ("ask", "who are you?")
    assert parse_chat_command("/teach my name is Alex") == ("teach", "my name is Alex")


def test_parse_chat_command_unknown_and_empty():
    assert parse_chat_command("hello") == ("unknown", "hello")
    assert parse_chat_command("   ") is None
