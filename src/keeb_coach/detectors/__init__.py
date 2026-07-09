"""Detectors turn parsed commands into ``Finding`` objects.

Each detector is a small, self-contained module that implements the
``Detector`` protocol from :mod:`keeb_coach.detectors.base`. Add a new
detector by dropping a file next to this one, exporting a subclass of
``Detector``, and registering it in :data:`ALL_DETECTORS` below.
"""

from __future__ import annotations

from .base import Detector, Finding, Severity
from .failed_retype import FailedRetypeDetector
from .long_path import LongPathDetector
from .missing_alias import MissingAliasDetector
from .slow_tool import SlowToolDetector
from .sudo_redo import SudoRedoDetector

# Registry order is stable and drives the default scoring/report ordering.
ALL_DETECTORS: tuple[Detector, ...] = (
    MissingAliasDetector(),
    SlowToolDetector(),
    LongPathDetector(),
    SudoRedoDetector(),
    FailedRetypeDetector(),
)

__all__ = [
    "ALL_DETECTORS",
    "Detector",
    "FailedRetypeDetector",
    "Finding",
    "LongPathDetector",
    "MissingAliasDetector",
    "Severity",
    "SlowToolDetector",
    "SudoRedoDetector",
]
