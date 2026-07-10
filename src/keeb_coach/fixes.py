"""Turn ``Finding`` objects into copy-paste alias/function snippets.

Consumed by the ``keeb-coach fixes`` subcommand. Two responsibilities,
kept in one module because they share a small vocabulary:

1. **Snippet generation.** :func:`snippets_for` maps each finding to a
   :class:`FixSnippet` (comment + one or more shell lines). We ship a
   handler per detector id; unknown detector ids are silently skipped
   so a future detector doesn't break the fixes command.
2. **Managed-block file writing.** :func:`write_managed_block` renders
   the snippets into a clearly-marked block and drops them into a
   *dedicated* file (never ``.bashrc`` / ``.zshrc`` / ``.profile`` —
   we refuse those explicitly). Re-running replaces the block in place
   so we're idempotent: no dupes, ever.

The block markers are stable and greppable:

.. code-block:: bash

    # >>> keeb-coach managed block >>>
    # ... snippets ...
    # <<< keeb-coach managed block <<<

Anything outside those markers is preserved untouched.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .detectors.base import Finding

# Markers are kept identical between the writer and the regex reader so
# users (and tests) can grep for either half unambiguously.
BLOCK_START = "# >>> keeb-coach managed block >>>"
BLOCK_END = "# <<< keeb-coach managed block <<<"

# Shell rc files we refuse to touch. The rule from PLAN.md is hard:
# never mutate the user's login shell config directly.
_FORBIDDEN_BASENAMES: frozenset[str] = frozenset(
    {
        ".bashrc",
        ".bash_profile",
        ".bash_login",
        ".profile",
        ".zshrc",
        ".zprofile",
        ".zshenv",
        ".zlogin",
        "config.fish",
    }
)

# For synthesized aliases we accept a narrow ASCII set only — anything
# else becomes an underscore. Keeps the aliases both valid POSIX names
# and safe to paste anywhere.
_ALIAS_SAFE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True)
class FixSnippet:
    """One coach-recommended fix, rendered as shell text.

    Attributes:
        detector: Stable id of the detector this came from (for grouping
            + tests).
        comment: One-line human-readable rationale, printed as a shell
            comment above the ``lines``.
        lines: Shell statements to source. Typically an ``alias`` or a
            comment-only nudge (for ``sudo_redo``).
        key: Stable de-dupe key so re-running with the same finding
            twice yields exactly one snippet in the managed block.
    """

    detector: str
    comment: str
    lines: tuple[str, ...]
    key: str


# ---------------------------------------------------------------------------
# Per-detector snippet builders
# ---------------------------------------------------------------------------


def _alias_slug(command: str) -> str:
    """Synthesize a short, POSIX-safe alias name from a command string.

    Strategy: take the first two argv tokens (``git status`` →
    ``git_status``), lowercase, replace anything non-``[a-z0-9_]`` with
    ``_``, collapse runs of ``_``, trim leading/trailing ``_``. Falls
    back to ``kc_alias`` if the result is empty (never happens in
    practice — the missing_alias detector requires ≥ 8 chars).
    """
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    head = "_".join(parts[:2]) if parts else command
    slug = _ALIAS_SAFE.sub("_", head.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug or "kc_alias"


def _snippet_missing_alias(finding: Finding) -> FixSnippet | None:
    """``alias <slug>='<command>'`` for the repeated invocation."""
    command = finding.evidence.get("command")
    if not isinstance(command, str) or not command:
        return None
    count = finding.evidence.get("count")
    count_str = f" ({count}×)" if isinstance(count, int) else ""
    slug = _alias_slug(command)
    return FixSnippet(
        detector=finding.detector,
        comment=f"missing_alias: retyped `{command}`{count_str}",
        lines=(f"alias {slug}={shlex.quote(command)}",),
        key=f"missing_alias::{slug}::{command}",
    )


def _snippet_slow_tool(finding: Finding) -> FixSnippet | None:
    """``alias <slow>='<replacement>'`` — swap the program transparently.

    We only alias when the ``slow`` side is a single token (``grep``,
    ``find``, ``cat``). Multi-token slow forms like ``ls -la`` can't be
    aliased safely (an ``alias 'ls -la'=`` doesn't work in POSIX), so
    we emit a nudge comment instead.
    """
    slow = finding.evidence.get("slow")
    replacement = finding.evidence.get("replacement")
    if not isinstance(slow, str) or not isinstance(replacement, str):
        return None
    if not slow or not replacement:
        return None
    tokens = slow.split()
    key = f"slow_tool::{slow}"
    comment = f"slow_tool: `{slow}` → `{replacement}`"
    if len(tokens) == 1:
        # Safe aliasable form: alias grep='rg'
        return FixSnippet(
            detector=finding.detector,
            comment=comment,
            lines=(f"alias {tokens[0]}={shlex.quote(replacement)}",),
            key=key,
        )
    # Multi-token: leave a comment-only reminder, no alias.
    return FixSnippet(
        detector=finding.detector,
        comment=comment + " (multi-token — swap manually)",
        lines=(f"# try: {replacement}",),
        key=key,
    )


def _snippet_long_path(finding: Finding) -> FixSnippet | None:
    """``alias to_<basename>='cd <target>'`` for retyped deep paths."""
    target = finding.evidence.get("target")
    if not isinstance(target, str) or not target:
        return None
    basename = target.rstrip("/").split("/")[-1] or "there"
    slug = _ALIAS_SAFE.sub("_", basename.lower()).strip("_") or "there"
    slug = f"to_{slug}"
    return FixSnippet(
        detector=finding.detector,
        comment=f"long_path: retyped `{target}` — jump alias",
        lines=(f"alias {slug}={shlex.quote('cd ' + target)}",),
        key=f"long_path::{slug}::{target}",
    )


def _snippet_sudo_redo(finding: Finding) -> FixSnippet | None:
    """No alias — shell already ships ``sudo !!``. Emit a nudge comment."""
    events = finding.evidence.get("events")
    count_str = f" ({events}×)" if isinstance(events, int) else ""
    return FixSnippet(
        detector=finding.detector,
        comment=f"sudo_redo: forgot sudo{count_str} — shortcut reminder",
        lines=(
            "# shortcut: `sudo !!` reruns the previous command as root",
        ),
        key="sudo_redo::reminder",
    )


def _snippet_failed_retype(finding: Finding) -> FixSnippet | None:
    """Nudge toward `fc`/`!!` instead of retyping failed commands."""
    count = finding.evidence.get("count")
    count_str = f" ({count}×)" if isinstance(count, int) else ""
    return FixSnippet(
        detector=finding.detector,
        comment=f"failed_retype: failure-then-retype pairs{count_str}",
        lines=(
            "# shortcuts you already have:",
            "#   !!   rerun previous command (great after `sudo`)",
            "#   fc   pop the previous command into $EDITOR for a real fix",
        ),
        key="failed_retype::reminder",
    )


# Registry: detector id → builder. Keeping it a plain dict means adding
# a new detector's fix handler is a one-line change.
_BUILDERS = {
    "missing_alias": _snippet_missing_alias,
    "slow_tool": _snippet_slow_tool,
    "long_path": _snippet_long_path,
    "sudo_redo": _snippet_sudo_redo,
    "failed_retype": _snippet_failed_retype,
}


def snippets_for(findings: Iterable[Finding]) -> list[FixSnippet]:
    """Convert a batch of findings into a de-duped snippet list.

    - Findings from unknown detectors are silently skipped.
    - Duplicates (same :attr:`FixSnippet.key`) collapse to the first one
      seen, so upstream can pass sorted findings and get a stable
      order in the output.
    """
    seen: set[str] = set()
    out: list[FixSnippet] = []
    for finding in findings:
        builder = _BUILDERS.get(finding.detector)
        if builder is None:
            continue
        snippet = builder(finding)
        if snippet is None:
            continue
        if snippet.key in seen:
            continue
        seen.add(snippet.key)
        out.append(snippet)
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_block(snippets: Sequence[FixSnippet]) -> str:
    """Render ``snippets`` into the managed-block body (no markers).

    Empty snippets → single reassuring comment so the block never
    ends up an empty pair of markers, which some editors treat as a
    truncated file.
    """
    if not snippets:
        return "# (no findings — nothing to alias right now)\n"
    parts: list[str] = []
    for snippet in snippets:
        parts.append(f"# {snippet.comment}")
        parts.extend(snippet.lines)
        parts.append("")  # blank line between snippets for readability
    return "\n".join(parts).rstrip() + "\n"


def render_full_block(snippets: Sequence[FixSnippet]) -> str:
    """Render the marker-wrapped block that goes into the file.

    The header carries a timestamp so users know when we last touched
    it — never used for parsing (start/end markers do that).
    """
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    body = render_block(snippets)
    return (
        f"{BLOCK_START}\n"
        f"# Generated by keeb-coach at {ts}. Re-run `keeb-coach fixes --write` to update.\n"
        f"# Everything between the >>> and <<< markers is overwritten on each run.\n"
        f"{body}"
        f"{BLOCK_END}\n"
    )


def render_stdout(snippets: Sequence[FixSnippet]) -> str:
    """Format snippets for the ``keeb-coach fixes`` (no --write) case.

    Same body as the file version, but wrapped in a friendly header
    that also documents the source-line the user would add to their
    rc file. Kept as a pure string so tests don't need a console.
    """
    header = (
        "# keeb-coach fixes — copy-paste these, or run `keeb-coach fixes --write PATH`.\n"
        "# Suggested target: ~/.keeb_aliases   (then add `source ~/.keeb_aliases` to your rc)\n"
    )
    if not snippets:
        return header + "# (no findings — nothing to alias right now)\n"
    return header + "\n" + render_block(snippets)


# ---------------------------------------------------------------------------
# Managed-block file I/O
# ---------------------------------------------------------------------------


class ForbiddenTargetError(ValueError):
    """Raised when the user tries to write into a shell rc file.

    Kept distinct from ``ValueError`` at the call-site so the CLI can
    turn it into a clean non-zero exit with a helpful message rather
    than a stack trace.
    """


def _reject_forbidden(target: Path) -> None:
    """Reject shell rc files by basename. Case-insensitive on macOS-safe."""
    name = target.name.lower()
    if name in _FORBIDDEN_BASENAMES:
        raise ForbiddenTargetError(
            f"refusing to write to {target} — keeb-coach never touches shell rc files. "
            f"Write to a dedicated file (e.g. ~/.keeb_aliases) and `source` it yourself."
        )


# Compiled once so re-runs on huge files don't pay the setup cost.
_BLOCK_RE = re.compile(
    rf"^{re.escape(BLOCK_START)}\n.*?^{re.escape(BLOCK_END)}\n?",
    flags=re.DOTALL | re.MULTILINE,
)


def _splice_block(existing: str, new_block: str) -> str:
    """Return ``existing`` with the managed block replaced or appended.

    - If a block exists, we swap it in place (preserving surrounding
      lines byte-for-byte).
    - If not, we append with a single blank line separator so the file
      stays readable when hand-edited later.
    - Multiple blocks (shouldn't happen, but paranoia is cheap): the
      first is replaced, extras are dropped so re-runs converge.
    """
    matches = list(_BLOCK_RE.finditer(existing))
    if matches:
        # Strip *all* existing blocks first (avoids the trap where
        # sub-then-sub-again wipes the block we just spliced in), then
        # splice the new block at the position of the first match.
        first_start = matches[0].start()
        stripped = _BLOCK_RE.sub("", existing)
        return stripped[:first_start] + new_block + stripped[first_start:]
    stripped = existing.rstrip()
    if not stripped:
        return new_block
    return f"{stripped}\n\n{new_block}"

def _atomic_write(target: Path, content: str) -> None:
    """Write ``content`` to ``target`` via a temp-file rename.

    A crash mid-write must never leave the user's alias file half-
    populated (they'd source garbage into their shell). We write to a
    sibling temp file and ``os.replace`` it into place, which is atomic
    on POSIX and Windows.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    # Same-dir temp keeps the rename atomic (no cross-device moves).
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, target)
    except Exception:
        # Clean up the temp on any error so we don't leave litter behind.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def write_managed_block(target: Path, snippets: Sequence[FixSnippet]) -> Path:
    """Write / update the managed block in ``target``.

    Args:
        target: File to write into. Must not be a shell rc file
            (``.bashrc``, ``.zshrc``, ``.profile``, etc.) — we raise
            :class:`ForbiddenTargetError` otherwise.
        snippets: Snippets to render into the block. An empty sequence
            is legal — we still write a "no findings" comment inside
            the markers so users can tell the run succeeded.

    Returns:
        The resolved absolute path we actually wrote to.

    Raises:
        ForbiddenTargetError: ``target`` looks like a shell rc file.
    """
    resolved = target.expanduser()
    _reject_forbidden(resolved)
    resolved = resolved.resolve() if resolved.exists() else resolved.absolute()
    _reject_forbidden(resolved)  # re-check after resolve() (symlinks)

    new_block = render_full_block(snippets)
    if resolved.exists():
        try:
            existing = resolved.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    else:
        existing = ""

    updated = _splice_block(existing, new_block)
    _atomic_write(resolved, updated)
    return resolved
