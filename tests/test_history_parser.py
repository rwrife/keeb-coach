"""Golden tests for bash + zsh history parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from keeb_coach.history import parser
from keeb_coach.history.parser import Command, parse_file, parse_lines

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_bash_fixture_counts_and_top_command() -> None:
    commands = parse_file("bash", FIXTURES / "bash_history.txt")

    # 15 executable lines (10 with timestamp, 5 without).
    assert len(commands) == 15

    # Timestamp is picked up from the `#<epoch>` line above the command.
    first = commands[0]
    assert first.raw == "git status"
    assert first.argv == ("git", "status")
    assert first.ts == datetime(2024, 7, 2, 0, 0, tzinfo=UTC)

    # Commands after the timestamped block have no stamp attached.
    tail = commands[-1]
    assert tail.raw == "git status"
    assert tail.ts is None

    programs = [c.program for c in commands]
    assert programs.count("git") == 7
    assert programs.count("docker") == 2
    assert programs.count("ls") == 1


def test_parse_zsh_fixture_extended_format_and_ts() -> None:
    commands = parse_file("zsh", FIXTURES / "zsh_history.txt")

    # 15 command lines even though one uses a line-continuation.
    assert len(commands) == 15

    first = commands[0]
    assert first.raw == "git status"
    assert first.argv == ("git", "status")
    assert first.ts == datetime(2024, 7, 2, 0, 0, tzinfo=UTC)

    # The continuation line got merged into a single command.
    joined = commands[-2]
    assert joined.raw.startswith("echo hello")
    assert "world" in joined.raw
    assert joined.argv == ("echo", "hello", "world")


def test_parse_lines_handles_zsh_extended_format() -> None:
    lines = [": 1719878400:0;git status", ": 1719878500:2;ls -la"]
    commands = list(parse_lines("zsh", lines))
    assert [c.raw for c in commands] == ["git status", "ls -la"]
    assert commands[0].ts == datetime(2024, 7, 2, 0, 0, tzinfo=UTC)
    assert commands[1].ts == datetime(2024, 7, 2, 0, 1, 40, tzinfo=UTC)


def test_parse_lines_plain_zsh_when_extended_off() -> None:
    lines = ["git status", "ls"]
    commands = list(parse_lines("zsh", lines))
    assert [c.raw for c in commands] == ["git status", "ls"]
    assert all(c.ts is None for c in commands)


def test_parse_bash_ts_binds_to_next_command_only() -> None:
    lines = ["#1719878400", "git status", "ls"]
    commands = list(parse_lines("bash", lines))
    assert len(commands) == 2
    assert commands[0].ts == datetime(2024, 7, 2, 0, 0, tzinfo=UTC)
    assert commands[1].ts is None


def test_parse_skips_blank_lines() -> None:
    lines = ["git status", "", "  ", "ls"]
    commands = list(parse_lines("bash", lines))
    assert [c.raw for c in commands] == ["git status", "ls"]


def test_parse_handles_bad_quoting_without_raising() -> None:
    # Unclosed quote — safe_split falls back to whitespace split.
    lines = ['echo "unterminated']
    commands = list(parse_lines("bash", lines))
    assert len(commands) == 1
    assert commands[0].raw == 'echo "unterminated'
    assert commands[0].argv == ("echo", '"unterminated')


def test_zsh_metafied_utf8_is_decoded() -> None:
    # zsh saves `café` as e c a f \x83\xe9 (metafied 0xe9 = 0xc9 ^ 0x20 = 'É',
    # not quite — the actual metafied form for the UTF-8 byte 0xe9 is 0x83 0xc9,
    # since 0xe9 ^ 0x20 == 0xc9). Verify the decoder reverses that pattern.
    raw_line = "echo caf\x83\xc9"
    decoded = parser._decode_zsh_metafied(raw_line)
    assert decoded == "echo caf\xe9"


def test_command_program_is_none_for_empty_argv() -> None:
    c = Command(raw="", argv=())
    assert c.program is None


def test_parse_bash_bogus_ts_line_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = ["#not-a-timestamp", "git status"]
    commands = list(parse_lines("bash", lines))
    # `#not-a-timestamp` doesn't match the ts regex so it becomes a command.
    assert commands[0].raw == "#not-a-timestamp"
    assert commands[-1].raw == "git status"
