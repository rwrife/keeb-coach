"""Detect commands that get retyped often enough to deserve an alias.

Heuristic: normalize each command to its full argv (so ``git status`` is
distinct from ``git push``), and flag any invocation that runs at least
``min_count`` times and is at least ``min_length`` chars long.

Both thresholds are tunable via the ``[detectors.missing_alias]`` config
section (config plumbing lands in M4 — for now sensible defaults).
"""

from __future__ import annotations

import shlex
from collections import Counter
from collections.abc import Sequence

from ..history.parser import Command
from .base import Finding, Severity

# Kept small so the M3 fixture (~15 commands) produces observable findings
# without requiring gigantic history files in tests.
DEFAULT_MIN_COUNT = 4
DEFAULT_MIN_LENGTH = 8
# Cap: shell keywords / builtins we would never sensibly alias.
_ALIAS_BLOCKLIST = frozenset(
    {
        "cd",
        "pwd",
        "exit",
        "logout",
        "true",
        "false",
        ":",
        "source",
        ".",
        "export",
        "unset",
        "alias",
        "unalias",
        "history",
    }
)


def _normalize(cmd: Command) -> str | None:
    """Turn a Command into a stable string for counting.

    - Skip empty argv (blank lines, timestamps that slipped through).
    - Skip the shell built-ins in ``_ALIAS_BLOCKLIST`` where aliasing
      makes no sense.
    - Rebuild via ``shlex.join`` so quoting is normalized across
      histories (``'git' status`` and ``git status`` compare equal).
    """
    if not cmd.argv:
        return None
    program = cmd.argv[0]
    if program in _ALIAS_BLOCKLIST:
        return None
    return shlex.join(cmd.argv)


def _severity_for(count: int, min_count: int) -> Severity:
    """Bin severity by how egregiously often the command was retyped."""
    if count >= min_count * 4:
        return Severity.HIGH
    if count >= min_count * 2:
        return Severity.MEDIUM
    return Severity.LOW


class MissingAliasDetector:
    """Flag long-ish commands that were run many times without an alias."""

    id = "missing_alias"
    name = "Missing alias"

    def run(
        self,
        commands: Sequence[Command],
        config: dict[str, object] | None = None,
    ) -> list[Finding]:
        cfg = (config or {}).get(self.id, {}) if config else {}
        min_count = (
            int(cfg.get("min_count", DEFAULT_MIN_COUNT))
            if isinstance(cfg, dict)
            else DEFAULT_MIN_COUNT
        )
        min_length = (
            int(cfg.get("min_length", DEFAULT_MIN_LENGTH))
            if isinstance(cfg, dict)
            else DEFAULT_MIN_LENGTH
        )

        counter: Counter[str] = Counter()
        for cmd in commands:
            key = _normalize(cmd)
            if key is None or len(key) < min_length:
                continue
            counter[key] += 1

        findings: list[Finding] = []
        for command_str, count in counter.most_common():
            if count < min_count:
                # ``most_common`` returns descending — first miss ends it.
                break
            severity = _severity_for(count, min_count)
            findings.append(
                Finding(
                    detector=self.id,
                    severity=severity,
                    message=(
                        f"You typed `{command_str}` {count} times. "
                        f"You have hands. Alias it."
                    ),
                    evidence={"command": command_str, "count": count},
                )
            )
        return findings
