"""Read commands from an `atuin <https://atuin.sh>`_ SQLite history DB.

Atuin is a popular shell-history replacement that records much richer
data than bash/zsh's plain history files: **exit code**, **cwd**,
**duration**, **session id**, and **hostname** per command. Once the
user has atuin installed we can unlock a whole class of "did this
actually work?" detectors that a plain history file simply can't feed.

Design goals for this module:

- **Zero hard deps.** Atuin ships as a separate binary; we only read
  its DB via ``sqlite3`` from the stdlib. If the DB isn't there we
  return ``None`` \u2014 callers fall back to plain history.
- **Read-only, best-effort.** We open the DB in read-only URI mode so
  we can never corrupt a live atuin install. Rows with bad data are
  skipped, never raised.
- **Same ``Command`` model.** Consumers (detectors, scoring, report)
  never need to know whether a command came from atuin or bash.

Atuin's ``history`` table schema (stable since v0.x):

    id TEXT PRIMARY KEY,
    timestamp INTEGER,   -- nanoseconds since epoch
    duration  INTEGER,   -- nanoseconds
    exit      INTEGER,
    command   TEXT,
    cwd       TEXT,
    session   TEXT,
    hostname  TEXT,
    deleted_at INTEGER   -- non-NULL means tombstoned

We honor ``deleted_at`` and skip tombstoned rows.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .parser import Command, _safe_split


@dataclass(frozen=True)
class AtuinSource:
    """A discovered atuin history DB."""

    path: Path
    exists: bool


def default_atuin_db_path() -> Path:
    """Return the canonical atuin DB path for the current environment.

    Honors ``$XDG_DATA_HOME`` when set, otherwise falls back to
    ``~/.local/share`` \u2014 same rules atuin itself uses.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "atuin" / "history.db"


def find_atuin(path: Path | None = None) -> AtuinSource:
    """Locate an atuin DB, returning a source record either way.

    Args:
        path: Explicit override. When ``None``, uses
            :func:`default_atuin_db_path`.
    """
    target = path if path is not None else default_atuin_db_path()
    return AtuinSource(path=target, exists=target.exists())


def _ns_to_datetime(ns: int | None) -> datetime | None:
    if ns is None:
        return None
    try:
        # Atuin stores nanoseconds; datetime wants seconds (float ok).
        return datetime.fromtimestamp(int(ns) / 1_000_000_000, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _ns_to_ms(ns: int | None) -> int | None:
    if ns is None:
        return None
    try:
        return int(int(ns) // 1_000_000)
    except (ValueError, TypeError):
        return None


def _row_to_command(row: sqlite3.Row) -> Command | None:
    raw = row["command"]
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Command(
        raw=raw,
        argv=_safe_split(raw),
        ts=_ns_to_datetime(row["timestamp"]),
        exit_code=(int(row["exit"]) if row["exit"] is not None else None),
        cwd=(row["cwd"] if isinstance(row["cwd"], str) else None),
        duration_ms=_ns_to_ms(row["duration"]),
        session=(row["session"] if isinstance(row["session"], str) else None),
    )


def load_atuin(path: Path | None = None) -> list[Command]:
    """Return every non-deleted command from the atuin DB in time order.

    Returns an empty list when the DB doesn't exist or can't be opened;
    corrupt/bad rows are skipped rather than raised. The result is
    sorted oldest-first to match how bash/zsh history is normally
    consumed (so ``sudo_redo``-style adjacency detectors keep working).
    """
    src = find_atuin(path)
    if not src.exists:
        return []

    # Read-only URI mode \u2014 we never mutate atuin's DB.
    uri = f"file:{src.path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.DatabaseError:
        return []
    try:
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                "SELECT command, timestamp, duration, exit, cwd, session "
                "FROM history "
                "WHERE deleted_at IS NULL "
                "ORDER BY timestamp ASC"
            )
        except sqlite3.DatabaseError:
            # Older/newer schemas without deleted_at: try again w/o it.
            try:
                cur = conn.execute(
                    "SELECT command, timestamp, duration, exit, cwd, session "
                    "FROM history ORDER BY timestamp ASC"
                )
            except sqlite3.DatabaseError:
                return []
        out: list[Command] = []
        for row in cur:
            try:
                cmd = _row_to_command(row)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if cmd is not None:
                out.append(cmd)
        return out
    finally:
        conn.close()
