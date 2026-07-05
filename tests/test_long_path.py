"""Tests for the LongPathDetector."""

from __future__ import annotations

import shlex

from keeb_coach.detectors.base import Severity
from keeb_coach.detectors.long_path import LongPathDetector
from keeb_coach.history.parser import Command


def _cd(target: str) -> Command:
    raw = f"cd {target}"
    return Command(raw=raw, argv=tuple(shlex.split(raw)))


def test_flags_repeated_deep_absolute_target() -> None:
    commands = [_cd("/home/user/projects/keeb-coach") for _ in range(4)]
    findings = LongPathDetector().run(commands)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.detector == "long_path"
    assert finding.evidence["target"] == "/home/user/projects/keeb-coach"
    assert finding.evidence["count"] == 4
    assert "4 times" in finding.message


def test_flags_repeated_deep_relative_target() -> None:
    commands = [_cd("../../foo/bar") for _ in range(3)]
    findings = LongPathDetector().run(commands)
    assert len(findings) == 1
    assert findings[0].evidence["target"] == "../../foo/bar"


def test_ignores_shallow_paths() -> None:
    # Depth 2 is below the default min_depth of 3.
    findings = LongPathDetector().run([_cd("foo/bar") for _ in range(10)])
    assert findings == []


def test_ignores_infrequent_navigation() -> None:
    findings = LongPathDetector().run(
        [_cd("/a/b/c"), _cd("/x/y/z"), _cd("/i/j/k")]
    )
    assert findings == []


def test_ignores_cd_home_and_cd_dash() -> None:
    # `cd` alone and `cd -` are exactly the shortcuts we'd recommend —
    # never flag them, no matter how often the user does it.
    home = [Command(raw="cd", argv=("cd",)) for _ in range(20)]
    dash = [_cd("-") for _ in range(20)]
    assert LongPathDetector().run(home) == []
    assert LongPathDetector().run(dash) == []


def test_ignores_cd_with_options() -> None:
    # `cd -P /foo` has two arguments — we conservatively skip it.
    weird = Command(raw="cd -P /foo/bar/baz", argv=("cd", "-P", "/foo/bar/baz"))
    findings = LongPathDetector().run([weird for _ in range(10)])
    assert findings == []


def test_distinct_targets_produce_distinct_findings() -> None:
    commands = (
        [_cd("/a/b/c") for _ in range(3)]
        + [_cd("/x/y/z") for _ in range(3)]
    )
    findings = LongPathDetector().run(commands)
    targets = {f.evidence["target"] for f in findings}
    assert targets == {"/a/b/c", "/x/y/z"}


def test_severity_scales_with_frequency() -> None:
    hi = LongPathDetector().run([_cd("/a/b/c") for _ in range(12)])
    med = LongPathDetector().run([_cd("/a/b/c") for _ in range(6)])
    lo = LongPathDetector().run([_cd("/a/b/c") for _ in range(3)])
    assert hi[0].severity == Severity.HIGH
    assert med[0].severity == Severity.MEDIUM
    assert lo[0].severity == Severity.LOW


def test_config_overrides_thresholds() -> None:
    # Tighter min_count + shallower min_depth so a shallow path fires.
    findings = LongPathDetector().run(
        [_cd("foo/bar") for _ in range(2)],
        config={"long_path": {"min_count": 2, "min_depth": 2}},
    )
    assert len(findings) == 1
    assert findings[0].evidence["target"] == "foo/bar"


def test_bad_config_falls_back_to_defaults() -> None:
    # Garbage in the config sub-tree shouldn't crash.
    findings = LongPathDetector().run(
        [_cd("/a/b/c") for _ in range(3)],
        config={"long_path": {"min_count": "not-an-int", "min_depth": None}},
    )
    assert len(findings) == 1


def test_non_cd_commands_are_ignored() -> None:
    commands = [
        Command(raw="ls /a/b/c", argv=("ls", "/a/b/c")) for _ in range(10)
    ]
    assert LongPathDetector().run(commands) == []


def test_empty_input() -> None:
    assert LongPathDetector().run([]) == []
