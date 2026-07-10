"""Detect commands that fail and then get retyped nearly verbatim.

Only meaningful when the history source records exit codes \u2014 today
that means the :mod:`keeb_coach.history.atuin` loader. Plain bash/zsh
history has no exit-code column, so this detector no-ops there and
never produces false positives (see ``Command.failed``).

Heuristic:

- Walk the timeline in order.
- For each command with a non-zero ``exit_code``, look at the next
  ``lookahead`` commands (default 3).
- If any of those has a *very similar* raw command line, count it as
  a "failed retype" pair \u2014 the user hit an error and immediately
  tried again with a small tweak (typo fix, missing sudo, wrong path,
  \u2026).
- Fire a finding when the total pair count clears ``min_count``.

Similarity uses ``difflib.SequenceMatcher.ratio()`` \u2014 cheap, stdlib,
and gives us a good "same command with a small edit" signal without
pulling in Levenshtein deps.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher

from ..history.parser import Command
from .base import Finding, Severity

DEFAULT_MIN_COUNT = 3
DEFAULT_LOOKAHEAD = 3
# Ratio 0.75 catches "gti status" \u2192 "git status", "sudo apt" after "apt",
# and path typos, without matching two totally different commands.
DEFAULT_MIN_SIMILARITY = 0.75


def _similar(a: str, b: str, threshold: float) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(a=a, b=b).ratio() >= threshold


def _severity_for(count: int, min_count: int) -> Severity:
    if count >= min_count * 4:
        return Severity.HIGH
    if count >= min_count * 2:
        return Severity.MEDIUM
    return Severity.LOW


class FailedRetypeDetector:
    """Flag habit of running a command, watching it fail, then retrying.

    Requires exit-code data (currently atuin-only). When no commands
    have ``exit_code`` set we return zero findings \u2014 no signal, no
    noise.
    """

    id = "failed_retype"
    name = "Failed retype"

    def run(
        self,
        commands: Sequence[Command],
        config: dict[str, object] | None = None,
    ) -> list[Finding]:
        raw_cfg = (config or {}).get(self.id, {}) if config else {}
        cfg = raw_cfg if isinstance(raw_cfg, Mapping) else {}
        min_count = int(cfg.get("min_count", DEFAULT_MIN_COUNT))
        lookahead = max(1, int(cfg.get("lookahead", DEFAULT_LOOKAHEAD)))
        threshold = float(cfg.get("min_similarity", DEFAULT_MIN_SIMILARITY))

        # Bail early if this history source has no exit-code info at all.
        if not any(c.exit_code is not None for c in commands):
            return []

        pairs: list[tuple[str, str]] = []
        n = len(commands)
        for i, cmd in enumerate(commands):
            if not cmd.failed or not cmd.raw.strip():
                continue
            for j in range(i + 1, min(n, i + 1 + lookahead)):
                candidate = commands[j]
                if not candidate.raw.strip():
                    continue
                if _similar(cmd.raw.strip(), candidate.raw.strip(), threshold):
                    pairs.append((cmd.raw.strip(), candidate.raw.strip()))
                    break  # one retype per failure is enough

        if len(pairs) < min_count:
            return []

        # Sample a few for the message so the coach shows their work
        # without dumping the whole timeline.
        sample = pairs[:3]
        preview = "; ".join(f"`{a}` \u2192 `{b}`" for a, b in sample)
        severity = _severity_for(len(pairs), min_count)
        return [
            Finding(
                detector=self.id,
                severity=severity,
                message=(
                    f"Caught {len(pairs)} failed-then-retyped command(s). "
                    f"e.g. {preview}. Slow down, or wire up "
                    "`command_not_found_handler` / `thefuck` for the typos."
                ),
                evidence={
                    "pairs": pairs,
                    "count": len(pairs),
                    "sample": sample,
                },
            )
        ]
