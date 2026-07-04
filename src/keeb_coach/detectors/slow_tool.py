"""Detect calls to legacy tools that have modern, faster equivalents.

The default map covers the "type less, think more" trio-of-trios called
out in PLAN.md: ``grep→rg``, ``find→fd``, ``cat→bat``, ``ls -la→eza``.

Matching is deliberately conservative:

- We only match the *program* (argv[0]) for single-word replacements
  like ``grep``. We never rewrite a pipeline for the user — we just
  flag that they typed the slow tool.
- Two-token slow tools (``ls -la``) match only when argv[0..1] matches.
- Piped commands aren't excluded — if you called ``grep`` inside a
  pipeline you can still swap it for ``rg``.

Config extension is trivial: drop new entries into
``[detectors.slow_tool.replacements]`` (wired in M4).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..history.parser import Command
from .base import Finding, Severity

# Order matters: multi-token entries are checked first so ``ls -la`` wins
# over ``ls``. The values are (replacement, one-liner why).
DEFAULT_REPLACEMENTS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("ls", "-la"), "eza -la", "eza has colors, icons, and git-awareness."),
    (("grep",), "rg", "ripgrep is faster and respects .gitignore by default."),
    (("find",), "fd", "fd has saner defaults, faster walking, and colored output."),
    (("cat",), "bat", "bat is cat with syntax highlighting + paging."),
)

# Flag if the slow tool appears at least this many times.
DEFAULT_MIN_COUNT = 3


@dataclass(frozen=True)
class _Rule:
    prefix: tuple[str, ...]
    replacement: str
    reason: str

    def matches(self, argv: Sequence[str]) -> bool:
        if len(argv) < len(self.prefix):
            return False
        return tuple(argv[: len(self.prefix)]) == self.prefix


def _load_rules(cfg: Mapping[str, object] | None) -> list[_Rule]:
    """Merge user config into the default rule list.

    Config shape (M4 wires this in, kept forward-compatible):

        [detectors.slow_tool]
        min_count = 3
        [detectors.slow_tool.replacements]
        "ls -la" = "eza -la"
        "grep" = "rg"
    """
    rules = [_Rule(prefix=p, replacement=r, reason=why) for (p, r, why) in DEFAULT_REPLACEMENTS]
    if not cfg:
        return rules
    extra = cfg.get("replacements") if isinstance(cfg, Mapping) else None
    if not isinstance(extra, Mapping):
        return rules
    # User-provided rules take precedence over defaults with the same prefix.
    overridden: list[_Rule] = []
    seen_prefixes: set[tuple[str, ...]] = set()
    for raw_key, raw_val in extra.items():
        if not isinstance(raw_key, str) or not isinstance(raw_val, str):
            continue
        prefix = tuple(raw_key.split())
        if not prefix:
            continue
        overridden.append(_Rule(prefix=prefix, replacement=raw_val, reason="from user config"))
        seen_prefixes.add(prefix)
    keep_defaults = [r for r in rules if r.prefix not in seen_prefixes]
    merged = overridden + keep_defaults
    # Longest prefix first so multi-token rules always win.
    merged.sort(key=lambda r: -len(r.prefix))
    return merged


def _severity_for(count: int, min_count: int) -> Severity:
    if count >= min_count * 4:
        return Severity.HIGH
    if count >= min_count * 2:
        return Severity.MEDIUM
    return Severity.LOW


class SlowToolDetector:
    """Flag legacy CLI usage that has an obvious modern replacement."""

    id = "slow_tool"
    name = "Slow tool"

    def run(
        self,
        commands: Sequence[Command],
        config: dict[str, object] | None = None,
    ) -> list[Finding]:
        raw_cfg = (config or {}).get(self.id, {}) if config else {}
        cfg = raw_cfg if isinstance(raw_cfg, Mapping) else {}
        min_count = int(cfg.get("min_count", DEFAULT_MIN_COUNT))
        rules = _load_rules(cfg)

        # Bucket by the rule that matched — one finding per rule.
        counts: Counter[int] = Counter()
        for cmd in commands:
            if not cmd.argv:
                continue
            for idx, rule in enumerate(rules):
                if rule.matches(cmd.argv):
                    counts[idx] += 1
                    break

        findings: list[Finding] = []
        for idx, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            if count < min_count:
                continue
            rule = rules[idx]
            slow = " ".join(rule.prefix)
            severity = _severity_for(count, min_count)
            findings.append(
                Finding(
                    detector=self.id,
                    severity=severity,
                    message=(
                        f"You reached for `{slow}` {count} times. "
                        f"Try `{rule.replacement}` — {rule.reason}"
                    ),
                    evidence={
                        "slow": slow,
                        "replacement": rule.replacement,
                        "count": count,
                    },
                )
            )
        return findings
