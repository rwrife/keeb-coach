"""Turn ``Finding`` objects into a weighted score and a letter grade.

Scoring model (deliberately naive for M3, tunable in M4):

- Each finding subtracts ``SEVERITY_PENALTY[severity]`` points from a
  starting score of 100.
- The total is clamped to ``[0, 100]`` and mapped to a letter grade via
  the standard 90/80/70/60 bands.

There is no per-detector weight yet — every detector contributes on the
same scale. If M4 needs "long-path retype is worse than missing alias,"
add a ``DETECTOR_WEIGHT`` multiplier here without touching detectors.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .detectors.base import Finding, Severity

# Points deducted per finding, by severity.
SEVERITY_PENALTY: dict[Severity, int] = {
    Severity.LOW: 3,
    Severity.MEDIUM: 6,
    Severity.HIGH: 12,
}

STARTING_SCORE = 100

# (min_score, letter). First hit wins; keep sorted descending.
_GRADE_BANDS: tuple[tuple[int, str], ...] = (
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
)


@dataclass(frozen=True)
class Scorecard:
    """Final graded output for one ``score`` run."""

    score: int
    grade: str
    findings: tuple[Finding, ...]
    total_commands: int

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


def _grade_for(score: int) -> str:
    for threshold, letter in _GRADE_BANDS:
        if score >= threshold:
            return letter
    return "F"  # pragma: no cover — 0-band catches everything.


def score_findings(
    findings: Sequence[Finding],
    total_commands: int,
) -> Scorecard:
    """Compute a ``Scorecard`` from raw findings.

    ``total_commands`` is threaded through so the report layer can
    display it alongside the grade without re-parsing history.
    """
    penalty = sum(SEVERITY_PENALTY[f.severity] for f in findings)
    raw = STARTING_SCORE - penalty
    clamped = max(0, min(STARTING_SCORE, raw))
    return Scorecard(
        score=clamped,
        grade=_grade_for(clamped),
        # Sort worst-first so the report reads top-down: severity DESC,
        # then insertion order (stable via enumerate tie-breaker).
        findings=tuple(
            sorted(
                findings,
                key=lambda f: (-int(f.severity), f.detector),
            )
        ),
        total_commands=total_commands,
    )
