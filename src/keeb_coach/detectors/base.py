"""Detector protocol + ``Finding`` model.

A detector inspects a sequence of parsed commands and yields ``Finding``
objects describing a habit worth fixing. Findings are the sole currency
that scoring and reporting consume — detectors never render output
themselves.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol, runtime_checkable

from ..history.parser import Command


class Severity(IntEnum):
    """How bad a habit is. Higher = worse. Also drives scoring weight."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True)
class Finding:
    """One thing the coach thinks you should change.

    Attributes:
        detector: Stable id of the detector that produced this (used by
            the report + scoring layers).
        severity: How annoyed the coach is.
        message: One-line human-readable summary. Rendered verbatim.
        suggested_fix: Optional copy-paste snippet (alias/function) —
            reserved for the M5 ``fixes`` command; harmless to set now.
        evidence: Optional structured payload (counts, sample commands)
            for tests + future JSON output. Never rendered directly.
    """

    detector: str
    severity: Severity
    message: str
    suggested_fix: str | None = None
    evidence: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class Detector(Protocol):
    """Protocol every detector implements.

    Kept minimal on purpose: a stable ``id``, a human ``name``, and a
    ``run`` method that returns findings for the given commands. Config
    is passed in as a plain dict so we can swap TOML for anything else
    without touching detector code.
    """

    id: str
    name: str

    def run(
        self,
        commands: Sequence[Command],
        config: dict[str, object] | None = None,
    ) -> list[Finding]:
        """Analyze ``commands`` and return zero or more findings."""
        ...
