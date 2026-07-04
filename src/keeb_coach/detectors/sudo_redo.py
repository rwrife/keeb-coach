"""Detect the classic "forgot sudo, retyped the whole thing" pattern.

We look for adjacency in the raw history: any command immediately
followed by ``sudo !!`` (or the retyped ``sudo <same-command>``) is
one point of evidence that the user forgot sudo. Any command
immediately followed by a ``sudo``-prefixed version of the same
command counts too — that's the "retype" the ``sudo !!`` shortcut
would have avoided.

Config surface (``[detectors.sudo_redo]``):

- ``min_count`` — how many adjacency events before we file a finding
  (default 2 — this pattern is rare in a healthy history).
"""

from __future__ import annotations

import shlex
from collections import Counter
from collections.abc import Mapping, Sequence

from ..history.parser import Command
from .base import Finding, Severity

DEFAULT_MIN_COUNT = 2

# The two literal forms that mean "run the previous line as root".
_SUDO_BANG_BANG = ("sudo !!", "sudo !!;", "sudo !!;\n")


def _is_sudo_bang_bang(cmd: Command) -> bool:
    """True if this is a literal ``sudo !!`` invocation."""
    raw = cmd.raw.strip()
    if raw in _SUDO_BANG_BANG:
        return True
    # ``argv`` splitting drops the ``!!`` — fall back to raw match.
    return raw.startswith("sudo") and "!!" in raw


def _sudo_wraps(prev: Command, curr: Command) -> bool:
    """True if ``curr`` is the ``sudo``-prefixed retype of ``prev``.

    We compare via ``shlex.join`` so quoting differences don't fool us,
    and we require ``prev`` to *not* already start with sudo (otherwise
    every ``sudo apt update; sudo apt upgrade`` sequence would fire).
    """
    if not prev.argv or not curr.argv:
        return False
    if prev.argv[0] == "sudo":
        return False
    if curr.argv[0] != "sudo" or len(curr.argv) < 2:
        return False
    prev_joined = shlex.join(prev.argv)
    curr_joined = shlex.join(curr.argv[1:])
    return prev_joined == curr_joined


def _severity_for(count: int, min_count: int) -> Severity:
    if count >= min_count * 4:
        return Severity.HIGH
    if count >= min_count * 2:
        return Severity.MEDIUM
    return Severity.LOW


class SudoRedoDetector:
    """Flag the ``cmd`` → ``sudo !!`` / ``sudo cmd`` retype pattern."""

    id = "sudo_redo"
    name = "Sudo redo"

    def run(
        self,
        commands: Sequence[Command],
        config: dict[str, object] | None = None,
    ) -> list[Finding]:
        raw_cfg = (config or {}).get(self.id, {}) if config else {}
        cfg = raw_cfg if isinstance(raw_cfg, Mapping) else {}
        try:
            min_count = int(cfg.get("min_count", DEFAULT_MIN_COUNT))
        except (TypeError, ValueError):
            min_count = DEFAULT_MIN_COUNT

        bang_bangs = 0
        # Track which commands most often needed the sudo retype so we
        # can surface the top offender in the evidence.
        retyped: Counter[str] = Counter()
        prev: Command | None = None
        for cmd in commands:
            if prev is not None:
                if _is_sudo_bang_bang(cmd) and prev.argv:
                    bang_bangs += 1
                    # Bang-bang counts as a retype event too — the user
                    # still noticed sudo was missing, they just used
                    # the shortcut. Track the underlying command.
                    retyped[shlex.join(prev.argv)] += 1
                elif _sudo_wraps(prev, cmd):
                    retyped[shlex.join(prev.argv)] += 1
            prev = cmd

        # ``retyped`` counts every event (bang-bang uses included);
        # ``bang_bangs`` is a subset that used the shortcut.
        total_events = sum(retyped.values())
        if total_events < min_count:
            return []

        top_cmd, top_count = retyped.most_common(1)[0]
        severity = _severity_for(total_events, min_count)
        example = (
            f"most often after `{top_cmd}` ({top_count}×)"
            if top_count > 1
            else f"e.g. after `{top_cmd}`"
        )
        return [
            Finding(
                detector=self.id,
                severity=severity,
                message=(
                    f"You forgot `sudo` and retyped {total_events} times — {example}. "
                    f"Muscle-memory `sudo !!` next time."
                ),
                suggested_fix="# shell shortcut: `sudo !!` reruns the last command as root",
                evidence={
                    "events": total_events,
                    "bang_bang_uses": bang_bangs,
                    "top_command": top_cmd,
                    "top_count": top_count,
                },
            )
        ]
