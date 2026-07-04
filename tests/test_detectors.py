"""Tests for the MissingAlias + SlowTool detectors."""

from __future__ import annotations

import pytest

from keeb_coach.detectors.base import Finding, Severity
from keeb_coach.detectors.missing_alias import MissingAliasDetector
from keeb_coach.detectors.slow_tool import SlowToolDetector
from keeb_coach.history.parser import Command


def _cmd(raw: str) -> Command:
    """Convenience factory — argv split matches parser behavior."""
    import shlex

    return Command(raw=raw, argv=tuple(shlex.split(raw)))


# ---------------------------------------------------------------------------
# MissingAliasDetector
# ---------------------------------------------------------------------------


def test_missing_alias_flags_repeated_long_command() -> None:
    commands = [_cmd("git status") for _ in range(5)]
    findings = MissingAliasDetector().run(commands)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.detector == "missing_alias"
    assert "git status" in finding.message
    assert "5 times" in finding.message
    assert finding.evidence["count"] == 5


def test_missing_alias_ignores_infrequent_commands() -> None:
    commands = [_cmd("git status"), _cmd("git push origin main")]
    findings = MissingAliasDetector().run(commands)
    assert findings == []


def test_missing_alias_ignores_short_commands() -> None:
    # `ls` alone is 2 chars — well below the default min_length.
    commands = [_cmd("ls") for _ in range(10)]
    findings = MissingAliasDetector().run(commands)
    assert findings == []


def test_missing_alias_ignores_blocklisted_builtins() -> None:
    commands = [_cmd("cd /home/user/projects") for _ in range(10)]
    findings = MissingAliasDetector().run(commands)
    assert findings == []


def test_missing_alias_distinguishes_argv() -> None:
    # `git status` × 4 and `git push` × 4 should each fire independently.
    commands = [_cmd("git status") for _ in range(4)] + [_cmd("git push origin") for _ in range(4)]
    findings = MissingAliasDetector().run(commands)
    commands_flagged = {f.evidence["command"] for f in findings}
    assert commands_flagged == {"git status", "git push origin"}


def test_missing_alias_severity_scales_with_frequency() -> None:
    # Default min_count=4. min_count*4=16 crosses into HIGH.
    hi = MissingAliasDetector().run([_cmd("git status") for _ in range(20)])
    med = MissingAliasDetector().run([_cmd("git status") for _ in range(8)])
    lo = MissingAliasDetector().run([_cmd("git status") for _ in range(4)])
    assert hi[0].severity == Severity.HIGH
    assert med[0].severity == Severity.MEDIUM
    assert lo[0].severity == Severity.LOW


def test_missing_alias_respects_config_overrides() -> None:
    # Tighten min_count to 2 so a mere pair triggers.
    findings = MissingAliasDetector().run(
        [_cmd("git status"), _cmd("git status")],
        config={"missing_alias": {"min_count": 2, "min_length": 5}},
    )
    assert len(findings) == 1
    assert findings[0].evidence["count"] == 2


def test_missing_alias_handles_empty_input() -> None:
    assert MissingAliasDetector().run([]) == []


def test_missing_alias_skips_empty_argv() -> None:
    # Direct Command with no argv (shouldn't normally happen but be defensive).
    empty = Command(raw="", argv=())
    findings = MissingAliasDetector().run([empty] * 10)
    assert findings == []


# ---------------------------------------------------------------------------
# SlowToolDetector
# ---------------------------------------------------------------------------


def test_slow_tool_flags_grep_when_over_threshold() -> None:
    commands = [_cmd(f'grep -r "TODO{i}" src/') for i in range(4)]
    findings = SlowToolDetector().run(commands)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.detector == "slow_tool"
    assert finding.evidence["slow"] == "grep"
    assert finding.evidence["replacement"] == "rg"
    assert finding.evidence["count"] == 4


def test_slow_tool_ignores_infrequent_use() -> None:
    findings = SlowToolDetector().run([_cmd("grep foo bar.txt")])
    assert findings == []


def test_slow_tool_matches_multi_token_prefix_first() -> None:
    # `ls -la` should match the eza rule, not fall through to a lone `ls`.
    commands = [_cmd("ls -la") for _ in range(3)]
    findings = SlowToolDetector().run(commands)
    assert len(findings) == 1
    assert findings[0].evidence["slow"] == "ls -la"
    assert findings[0].evidence["replacement"] == "eza -la"


def test_slow_tool_multiple_rules_produce_multiple_findings() -> None:
    commands = (
        [_cmd(f"find . -name f{i}") for i in range(3)]
        + [_cmd(f"cat file{i}.txt") for i in range(4)]
    )
    findings = SlowToolDetector().run(commands)
    slows = {f.evidence["slow"] for f in findings}
    assert slows == {"find", "cat"}
    # Findings should be sorted highest-count first.
    assert findings[0].evidence["slow"] == "cat"
    assert findings[0].evidence["count"] == 4


def test_slow_tool_severity_scales_with_frequency() -> None:
    hi = SlowToolDetector().run([_cmd("grep foo bar")] * 12)
    med = SlowToolDetector().run([_cmd("grep foo bar")] * 6)
    lo = SlowToolDetector().run([_cmd("grep foo bar")] * 3)
    assert hi[0].severity == Severity.HIGH
    assert med[0].severity == Severity.MEDIUM
    assert lo[0].severity == Severity.LOW


def test_slow_tool_honors_user_replacement_override() -> None:
    findings = SlowToolDetector().run(
        [_cmd("cat file.txt")] * 3,
        config={"slow_tool": {"replacements": {"cat": "batcat"}}},
    )
    assert len(findings) == 1
    assert findings[0].evidence["replacement"] == "batcat"


def test_slow_tool_honors_min_count_override() -> None:
    findings = SlowToolDetector().run(
        [_cmd("grep foo bar")],
        config={"slow_tool": {"min_count": 1}},
    )
    assert len(findings) == 1


def test_slow_tool_ignores_bad_config_shapes() -> None:
    # Non-dict config values should not crash the detector.
    findings = SlowToolDetector().run(
        [_cmd("grep foo bar")] * 3,
        config={"slow_tool": "not-a-dict"},  # type: ignore[dict-item]
    )
    assert len(findings) == 1  # falls back to defaults


def test_slow_tool_ignores_pipeline_second_program() -> None:
    # `cat foo | grep x` shows up in history as one Command; argv[0] is `cat`.
    # We match on argv[0], so grep inside a pipeline isn't double-counted.
    commands = [_cmd("cat foo") for _ in range(3)] + [_cmd("grep x foo") for _ in range(3)]
    findings = SlowToolDetector().run(commands)
    slows = {f.evidence["slow"] for f in findings}
    assert slows == {"cat", "grep"}


def test_slow_tool_finding_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    findings = SlowToolDetector().run([_cmd("grep foo")] * 3)
    assert isinstance(findings[0], Finding)
    with pytest.raises(FrozenInstanceError):
        findings[0].message = "changed"  # type: ignore[misc]
