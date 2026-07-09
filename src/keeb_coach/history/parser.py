"""Normalize raw shell history lines into ``Command`` records.

Supports two formats in M2:

- **bash** — one command per line. `HISTTIMEFORMAT` optionally prefixes each
  command with a timestamp line ``#<epoch>`` on its own row; we handle both.
- **zsh** — either plain lines (like bash) or the "extended history" format:
  ``: <epoch>:<duration>;<cmd>``. Multi-line commands are joined via a
  trailing backslash on the previous physical line (zsh's own convention).

We intentionally keep parsing tolerant: bad lines are skipped rather than
raising, so a corrupt tail on a live history file never breaks scoring.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# `: 1719878400:0;git status` (DOTALL so multi-line commands are captured intact)
_ZSH_EXTENDED_RE = re.compile(r"^:\s+(?P<ts>\d+):(?P<dur>\d+);(?P<cmd>.*)$", re.DOTALL)
# `#1719878400`
_BASH_TS_RE = re.compile(r"^#(?P<ts>\d{9,})\s*$")


@dataclass(frozen=True)
class Command:
    """One normalized command from a history file.

    The four "rich" fields (``exit_code``, ``cwd``, ``duration_ms``,
    ``session``) are populated only by richer history sources such as
    :mod:`keeb_coach.history.atuin`. Plain bash/zsh history files never
    set them, so downstream code must treat them as optional.
    """

    raw: str
    argv: tuple[str, ...] = field(default_factory=tuple)
    ts: datetime | None = None
    exit_code: int | None = None
    cwd: str | None = None
    duration_ms: int | None = None
    session: str | None = None

    @property
    def program(self) -> str | None:
        """First argv token, if any — the invoked program/builtin."""
        return self.argv[0] if self.argv else None

    @property
    def failed(self) -> bool:
        """True when we have an exit code and it's non-zero.

        Commands without exit-code info (bash/zsh history) return
        ``False`` — we never *invent* failure.
        """
        return self.exit_code is not None and self.exit_code != 0


def _safe_split(raw: str) -> tuple[str, ...]:
    """Best-effort shell split. Falls back to whitespace split on bad quoting."""
    try:
        return tuple(shlex.split(raw, posix=True))
    except ValueError:
        return tuple(raw.split())


def _ts_from_epoch(epoch: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(epoch), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _decode_zsh_metafied(raw: str) -> str:
    """Decode zsh's "metafied" escape (0x83 + (byte ^ 0x20)) if present.

    zsh saves non-ASCII bytes with a 0x83 prefix + the byte XOR'd with 0x20.
    Round-tripped as text this shows up as ``\u0083<char>``. Very common with
    UTF-8 commands. We do a cheap pass to reverse it so ``echo café`` parses
    intact.
    """
    if "\x83" not in raw:
        return raw
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\x83" and i + 1 < len(raw):
            nxt = raw[i + 1]
            out.append(chr(ord(nxt) ^ 0x20))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _iter_logical_lines(lines: Iterable[str]) -> Iterator[str]:
    """Merge trailing-backslash continuations into one logical line.

    zsh writes multi-line commands with a literal ``\\`` at EOL and continues
    the command on the next physical line. Bash with ``cmdhist`` typically
    stores them on a single line already, but we handle the join defensively
    for either shell.
    """
    buf: list[str] = []
    for physical in lines:
        stripped = physical.rstrip("\n")
        if stripped.endswith("\\"):
            buf.append(stripped[:-1])
            continue
        if buf:
            buf.append(stripped)
            yield "\n".join(buf)
            buf = []
        else:
            yield stripped
    if buf:
        yield "\n".join(buf)


def _parse_bash(logical: Iterable[str]) -> Iterator[Command]:
    pending_ts: datetime | None = None
    for line in logical:
        if not line.strip():
            pending_ts = None
            continue
        m = _BASH_TS_RE.match(line)
        if m:
            pending_ts = _ts_from_epoch(m.group("ts"))
            continue
        yield Command(raw=line, argv=_safe_split(line), ts=pending_ts)
        pending_ts = None


def _parse_zsh(logical: Iterable[str]) -> Iterator[Command]:
    for line in logical:
        if not line.strip():
            continue
        decoded = _decode_zsh_metafied(line)
        m = _ZSH_EXTENDED_RE.match(decoded)
        if m:
            cmd = m.group("cmd")
            yield Command(raw=cmd, argv=_safe_split(cmd), ts=_ts_from_epoch(m.group("ts")))
            continue
        # Plain zsh history (extended format off) — treat like bash w/o ts.
        yield Command(raw=decoded, argv=_safe_split(decoded), ts=None)


def parse_lines(shell: str, lines: Iterable[str]) -> Iterator[Command]:
    """Parse raw lines from a history file for the given ``shell``."""
    logical = _iter_logical_lines(lines)
    if shell == "zsh":
        yield from _parse_zsh(logical)
    else:
        # bash + unknown share the same simple format.
        yield from _parse_bash(logical)


def parse_file(shell: str, path: Path) -> list[Command]:
    """Read ``path`` and return the parsed commands.

    Uses ``latin-1`` decoding so we never explode on stray non-UTF-8 bytes in a
    history file; the metafied-zsh decoder above then repairs zsh's own escaping.
    """
    with path.open("r", encoding="latin-1", errors="replace") as fh:
        return list(parse_lines(shell, fh))
