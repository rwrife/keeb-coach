"""Tests for the SudoRedoDetector."""

from __future__ import annotations

import shlex

from keeb_coach.detectors.base import Severity
from keeb_coach.detectors.sudo_redo import SudoRedoDetector
from keeb_coach.history.parser import Command


def _cmd(raw: str) -> Command:
    try:
        argv = tuple(shlex.split(raw))
    except ValueError:
        argv = tuple(raw.split())
    return Command(raw=raw, argv=argv)


def test_flags_cmd_followed_by_sudo_bang_bang() -> None:
    commands = [
        _cmd("apt update"),
        _cmd("sudo !!"),
        _cmd("apt install curl"),
        _cmd("sudo !!"),
    ]
    findings = SudoRedoDetector().run(commands)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.detector == "sudo_redo"
    assert finding.evidence["events"] == 2
    assert finding.evidence["bang_bang_uses"] == 2


def test_flags_cmd_followed_by_sudo_retype() -> None:
    # The pattern this detector really cares about: the user forgot
    # sudo and manually retyped the whole command.
    commands = [
        _cmd("apt update"),
        _cmd("sudo apt update"),
        _cmd("systemctl restart nginx"),
        _cmd("sudo systemctl restart nginx"),
    ]
    findings = SudoRedoDetector().run(commands)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.evidence["events"] == 2
    # No sudo !! shortcut was used, so bang_bang_uses stays at zero.
    assert finding.evidence["bang_bang_uses"] == 0


def test_ignores_infrequent_pattern() -> None:
    # Default min_count=2 — a single event isn't enough.
    findings = SudoRedoDetector().run(
        [_cmd("apt update"), _cmd("sudo apt update")]
    )
    assert findings == []


def test_does_not_flag_sudo_after_unrelated_command() -> None:
    commands = [
        _cmd("ls -la"),
        _cmd("sudo apt install curl"),
        _cmd("ls -la"),
        _cmd("sudo apt install wget"),
    ]
    assert SudoRedoDetector().run(commands) == []


def test_does_not_flag_two_sudo_commands_in_a_row() -> None:
    # ``sudo apt update; sudo apt upgrade`` shouldn't fire — the previous
    # command already used sudo, so no forgetting happened.
    commands = [
        _cmd("sudo apt update"),
        _cmd("sudo apt upgrade"),
        _cmd("sudo apt install curl"),
        _cmd("sudo apt install wget"),
    ]
    assert SudoRedoDetector().run(commands) == []


def test_severity_scales_with_event_count() -> None:
    def stream(n: int) -> list[Command]:
        cmds: list[Command] = []
        for i in range(n):
            cmds.append(_cmd(f"apt install pkg{i}"))
            cmds.append(_cmd(f"sudo apt install pkg{i}"))
        return cmds

    lo = SudoRedoDetector().run(stream(2))   # 2 events
    med = SudoRedoDetector().run(stream(4))  # 4 events (>= min_count*2)
    hi = SudoRedoDetector().run(stream(8))   # 8 events (>= min_count*4)
    assert lo[0].severity == Severity.LOW
    assert med[0].severity == Severity.MEDIUM
    assert hi[0].severity == Severity.HIGH


def test_config_overrides_min_count() -> None:
    findings = SudoRedoDetector().run(
        [_cmd("apt update"), _cmd("sudo apt update")],
        config={"sudo_redo": {"min_count": 1}},
    )
    assert len(findings) == 1


def test_bang_bang_and_retype_events_combine() -> None:
    commands = [
        _cmd("apt update"),
        _cmd("sudo !!"),
        _cmd("systemctl restart nginx"),
        _cmd("sudo systemctl restart nginx"),
    ]
    findings = SudoRedoDetector().run(commands)
    assert findings[0].evidence["events"] == 2
    assert findings[0].evidence["bang_bang_uses"] == 1


def test_reports_top_offender_command() -> None:
    commands = (
        [_cmd("apt update"), _cmd("sudo apt update")]
        + [_cmd("apt update"), _cmd("sudo apt update")]
        + [_cmd("systemctl status nginx"), _cmd("sudo systemctl status nginx")]
    )
    findings = SudoRedoDetector().run(commands)
    assert findings[0].evidence["top_command"] == "apt update"
    assert findings[0].evidence["top_count"] == 2


def test_message_mentions_sudo_bang_bang_suggestion() -> None:
    commands = [_cmd("apt update"), _cmd("sudo apt update"),
                _cmd("apt upgrade"), _cmd("sudo apt upgrade")]
    findings = SudoRedoDetector().run(commands)
    assert "sudo !!" in findings[0].message


def test_empty_input() -> None:
    assert SudoRedoDetector().run([]) == []
