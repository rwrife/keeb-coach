"""Locate the user's shell history file.

M1 scope: detection only — parsing lands in M2.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HistorySource:
    """A discovered shell history file."""

    shell: str  # "bash" | "zsh" | "fish" | "unknown"
    path: Path
    exists: bool


def detect_shell() -> str:
    """Best-effort shell detection from $SHELL."""
    shell_env = os.environ.get("SHELL", "")
    name = Path(shell_env).name if shell_env else ""
    if name in {"bash", "zsh", "fish"}:
        return name
    return "unknown"


def _candidate_paths(shell: str) -> list[Path]:
    home = Path.home()
    if shell == "bash":
        return [
            Path(os.environ["HISTFILE"]) if os.environ.get("HISTFILE") else home / ".bash_history",
        ]
    if shell == "zsh":
        return [
            Path(os.environ["HISTFILE"]) if os.environ.get("HISTFILE") else home / ".zsh_history",
        ]
    if shell == "fish":
        xdg = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
        return [Path(xdg) / "fish" / "fish_history"]
    # unknown — try the common ones in order
    return [
        home / ".zsh_history",
        home / ".bash_history",
    ]


def find_history() -> HistorySource:
    """Return the first-hit history source for the current environment."""
    shell = detect_shell()
    for candidate in _candidate_paths(shell):
        if candidate.exists():
            return HistorySource(shell=shell, path=candidate, exists=True)
    # Nothing found — still return the primary candidate so the CLI can report it.
    primary = _candidate_paths(shell)[0]
    return HistorySource(shell=shell, path=primary, exists=False)
