"""Tests for scoring + report."""

from __future__ import annotations

import io

from rich.console import Console

from keeb_coach.detectors.base import Finding, Severity
from keeb_coach.report import render_scorecard
from keeb_coach.scoring import SEVERITY_PENALTY, STARTING_SCORE, score_findings


def _finding(sev: Severity, detector: str = "missing_alias", msg: str = "meh") -> Finding:
    return Finding(detector=detector, severity=sev, message=msg)


def test_score_no_findings_is_perfect() -> None:
    scorecard = score_findings([], total_commands=42)
    assert scorecard.score == STARTING_SCORE
    assert scorecard.grade == "A"
    assert scorecard.total_commands == 42
    assert not scorecard.has_findings


def test_score_penalty_matches_severity_table() -> None:
    findings = [_finding(Severity.HIGH), _finding(Severity.MEDIUM), _finding(Severity.LOW)]
    scorecard = score_findings(findings, total_commands=100)
    expected = (
        STARTING_SCORE
        - SEVERITY_PENALTY[Severity.HIGH]
        - SEVERITY_PENALTY[Severity.MEDIUM]
        - SEVERITY_PENALTY[Severity.LOW]
    )
    assert scorecard.score == expected


def test_score_is_clamped_to_zero() -> None:
    findings = [_finding(Severity.HIGH) for _ in range(100)]  # 1200-pt penalty
    scorecard = score_findings(findings, total_commands=999)
    assert scorecard.score == 0
    assert scorecard.grade == "F"


def test_grade_bands() -> None:
    # 100 → A, 89 → B, 79 → C, 69 → D, 59 → F.
    def grade(score: int) -> str:
        # Reconstruct via a synthetic penalty count on LOW (3 pts each).
        num = (STARTING_SCORE - score) // SEVERITY_PENALTY[Severity.LOW]
        findings = [_finding(Severity.LOW) for _ in range(num)]
        return score_findings(findings, total_commands=1).grade

    assert grade(100) == "A"
    assert grade(88) == "B"  # 4 LOW findings = 12 penalty
    assert grade(76) == "C"  # 8 LOW = 24
    assert grade(64) == "D"  # 12 LOW = 36
    assert grade(52) == "F"  # 16 LOW = 48


def test_findings_sorted_severity_desc() -> None:
    findings = [
        _finding(Severity.LOW, detector="low_a"),
        _finding(Severity.HIGH, detector="high_a"),
        _finding(Severity.MEDIUM, detector="med_a"),
    ]
    scorecard = score_findings(findings, total_commands=10)
    severities = [f.severity for f in scorecard.findings]
    assert severities == [Severity.HIGH, Severity.MEDIUM, Severity.LOW]


def test_render_scorecard_clean_sheet() -> None:
    console = Console(file=io.StringIO(), force_terminal=False, width=100)
    scorecard = score_findings([], total_commands=25)
    render_scorecard(scorecard, console)
    out = console.file.getvalue()
    assert "A" in out
    assert "100/100" in out
    assert "Clean sheet" in out
    assert "25 commands" in out


def test_render_scorecard_with_findings() -> None:
    console = Console(file=io.StringIO(), force_terminal=False, width=100)
    findings = [
        Finding(
            detector="missing_alias",
            severity=Severity.HIGH,
            message="You typed `git status` 20 times.",
        ),
        Finding(
            detector="slow_tool",
            severity=Severity.MEDIUM,
            message="Use ripgrep instead of grep.",
        ),
    ]
    scorecard = score_findings(findings, total_commands=50)
    render_scorecard(scorecard, console)
    out = console.file.getvalue()
    assert "missing_alias" in out
    assert "slow_tool" in out
    assert "git status" in out
    assert "ripgrep" in out
    assert "high" in out
    assert "med" in out
    # No "clean sheet" copy when findings exist.
    assert "Clean sheet" not in out
