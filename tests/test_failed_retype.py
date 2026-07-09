"""Tests for FailedRetypeDetector — atuin-fed, exit-code-aware."""

from __future__ import annotations

from keeb_coach.detectors.failed_retype import FailedRetypeDetector
from keeb_coach.history.parser import Command


def _c(raw: str, exit_code: int | None = 0) -> Command:
    return Command(raw=raw, argv=tuple(raw.split()), exit_code=exit_code)


def test_no_findings_when_no_exit_codes_available() -> None:
    # Simulates plain bash/zsh history — no exit codes anywhere.
    cmds = [Command(raw="gti status"), Command(raw="git status")]
    assert FailedRetypeDetector().run(cmds) == []


def test_flags_typo_then_correction() -> None:
    cmds = [
        _c("gti status", exit_code=127),
        _c("git status", exit_code=0),
        _c("gti log", exit_code=127),
        _c("git log", exit_code=0),
        _c("gti diff", exit_code=127),
        _c("git diff", exit_code=0),
    ]
    findings = FailedRetypeDetector().run(cmds)
    assert len(findings) == 1
    f = findings[0]
    assert f.detector == "failed_retype"
    assert f.evidence["count"] == 3


def test_ignores_unrelated_next_command() -> None:
    cmds = [
        _c("gti status", exit_code=127),
        _c("cd /tmp", exit_code=0),  # nothing similar in lookahead
        _c("ls", exit_code=0),
        _c("echo done", exit_code=0),
    ]
    assert FailedRetypeDetector().run(cmds) == []


def test_respects_min_count_config() -> None:
    cmds = [
        _c("gti status", exit_code=127),
        _c("git status", exit_code=0),
    ]
    # default min_count=3; this pair alone shouldn't fire.
    assert FailedRetypeDetector().run(cmds) == []
    # ...but lowering it via config should.
    cfg = {"failed_retype": {"min_count": 1}}
    findings = FailedRetypeDetector().run(cmds, cfg)
    assert len(findings) == 1
    assert findings[0].evidence["count"] == 1


def test_lookahead_window_bounded() -> None:
    # Retype happens 5 commands later — outside the default 3-command
    # lookahead — so nothing should fire.
    cmds = [
        _c("gti status", exit_code=127),
        _c("cd /tmp", exit_code=0),
        _c("ls", exit_code=0),
        _c("pwd", exit_code=0),
        _c("date", exit_code=0),
        _c("git status", exit_code=0),
    ]
    cfg = {"failed_retype": {"min_count": 1}}
    assert FailedRetypeDetector().run(cmds, cfg) == []


def test_severity_scales_with_pair_count() -> None:
    # 12 pairs at min_count=3 → severity HIGH (min*4).
    cmds: list[Command] = []
    for _ in range(12):
        cmds.append(_c("gti status", exit_code=127))
        cmds.append(_c("git status", exit_code=0))
    findings = FailedRetypeDetector().run(cmds)
    assert len(findings) == 1
    assert findings[0].severity.name == "HIGH"
