"""Detect ``cd`` targets that get retyped despite being long/deep.

Heuristic: only look at ``cd`` invocations, resolve the target
(``cd /a/b/c`` or ``cd ../../foo``), and flag any target whose *depth*
(``/``-separated segments after normalization) is ≥ ``min_depth`` and
that was navigated to ≥ ``min_count`` times.

We deliberately do *not* try to resolve ``~``/``$VARS``/relative paths
against a real cwd — we grade the keystrokes the user actually typed.
``~/projects/foo`` and ``/home/user/projects/foo`` are treated as
different targets because they *are* different amounts of typing.

We ignore ``cd`` with zero args (goes home) and ``cd -`` (already
using the shortcut we'd recommend). Anything else with a single arg
counts.

Config surface (``[detectors.long_path]``):

- ``min_count`` — retype threshold (default 3).
- ``min_depth`` — segments before the target is considered "long"
  (default 3).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from ..history.parser import Command
from .base import Finding, Severity

DEFAULT_MIN_COUNT = 3
DEFAULT_MIN_DEPTH = 3

# ``cd`` with zero args goes home; ``cd -`` is the fix we'd suggest.
_TRIVIAL_TARGETS = frozenset({"-", "~", ""})


def _target_depth(target: str) -> int:
    """Estimate how many path segments the user actually typed.

    We split on ``/`` and drop empty segments so ``/a/b/c``, ``a/b/c``,
    and ``a//b/c`` all count as depth 3. ``..`` and ``.`` count as real
    segments because they represent extra typing.
    """
    if not target:
        return 0
    return sum(1 for part in target.split("/") if part)


def _extract_target(cmd: Command) -> str | None:
    """Return the single-token cd target we care about, or ``None``.

    We keep this strict — anything unusual (``cd foo bar``, ``cd``
    inside a subshell string, etc.) is skipped rather than guessed at.
    """
    if not cmd.argv or cmd.argv[0] != "cd":
        return None
    if len(cmd.argv) != 2:
        # cd with 0 args goes home; cd with 2+ args is either an option
        # (`cd -P`) or malformed for our purposes — skip either way.
        return None
    target = cmd.argv[1]
    if target in _TRIVIAL_TARGETS:
        return None
    return target


def _severity_for(count: int, min_count: int) -> Severity:
    """Same three-band scaling used by the other detectors."""
    if count >= min_count * 4:
        return Severity.HIGH
    if count >= min_count * 2:
        return Severity.MEDIUM
    return Severity.LOW


class LongPathDetector:
    """Flag ``cd`` targets you keep retyping instead of ``cd -``/``zoxide``."""

    id = "long_path"
    name = "Long path retype"

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
        try:
            min_depth = int(cfg.get("min_depth", DEFAULT_MIN_DEPTH))
        except (TypeError, ValueError):
            min_depth = DEFAULT_MIN_DEPTH

        targets: Counter[str] = Counter()
        for cmd in commands:
            target = _extract_target(cmd)
            if target is None:
                continue
            if _target_depth(target) < min_depth:
                continue
            targets[target] += 1

        findings: list[Finding] = []
        for target, count in targets.most_common():
            if count < min_count:
                # Counter.most_common is desc — first miss ends it.
                break
            severity = _severity_for(count, min_count)
            findings.append(
                Finding(
                    detector=self.id,
                    severity=severity,
                    message=(
                        f"You navigated to `{target}` {count} times. "
                        f"Meet `cd -`, `zoxide`, or a shell variable."
                    ),
                    suggested_fix=(
                        f"# consider: alias to_last='cd -'  # or:  z {target.split('/')[-1]}"
                    ),
                    evidence={
                        "target": target,
                        "count": count,
                        "depth": _target_depth(target),
                    },
                )
            )
        return findings
