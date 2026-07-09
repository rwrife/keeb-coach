"""Tests for the atuin SQLite history loader."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from keeb_coach.history.atuin import (
    default_atuin_db_path,
    find_atuin,
    load_atuin,
)


def _make_atuin_db(
    path: Path,
    rows: list[tuple[str, int, int, int, str, str | None, str | None]],
    *,
    include_deleted_at: bool = True,
) -> None:
    """Build a minimal atuin-shaped DB at ``path``.

    ``rows`` is a list of ``(id, ts_ns, dur_ns, exit, command, cwd, session)``.
    Every row is inserted with ``deleted_at`` NULL unless we also insert
    tombstones (see the tombstone test).
    """
    conn = sqlite3.connect(path)
    try:
        if include_deleted_at:
            conn.execute(
                "CREATE TABLE history ("
                "id TEXT PRIMARY KEY, timestamp INTEGER, duration INTEGER, "
                "exit INTEGER, command TEXT, cwd TEXT, session TEXT, "
                "hostname TEXT, deleted_at INTEGER)"
            )
            for r in rows:
                conn.execute(
                    "INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*r, "host", None),
                )
        else:
            conn.execute(
                "CREATE TABLE history ("
                "id TEXT PRIMARY KEY, timestamp INTEGER, duration INTEGER, "
                "exit INTEGER, command TEXT, cwd TEXT, session TEXT, "
                "hostname TEXT)"
            )
            for r in rows:
                conn.execute(
                    "INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (*r, "host"),
                )
        conn.commit()
    finally:
        conn.close()


def test_find_atuin_missing(tmp_path: Path) -> None:
    src = find_atuin(tmp_path / "nope.db")
    assert not src.exists
    assert src.path == tmp_path / "nope.db"


def test_default_atuin_db_path_honors_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_atuin_db_path() == tmp_path / "atuin" / "history.db"


def test_load_atuin_returns_empty_when_missing(tmp_path: Path) -> None:
    assert load_atuin(tmp_path / "nope.db") == []


def test_load_atuin_parses_rows_in_time_order(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    # Deliberately insert out-of-order to prove we sort by timestamp.
    ts1 = 1_720_000_000_000_000_000
    ts2 = ts1 + 5_000_000_000  # +5s
    _make_atuin_db(
        db,
        [
            ("b", ts2, 42_000_000, 1, "gti status", "/home/u", "s1"),
            ("a", ts1, 12_000_000, 0, "git status", "/home/u", "s1"),
        ],
    )

    cmds = load_atuin(db)

    assert [c.raw for c in cmds] == ["git status", "gti status"]
    assert cmds[0].exit_code == 0
    assert cmds[0].failed is False
    assert cmds[1].exit_code == 1
    assert cmds[1].failed is True
    assert cmds[0].duration_ms == 12
    assert cmds[0].cwd == "/home/u"
    assert cmds[0].session == "s1"
    assert cmds[0].ts == datetime.fromtimestamp(ts1 / 1_000_000_000, tz=UTC)
    assert cmds[0].argv == ("git", "status")


def test_load_atuin_skips_tombstoned_rows(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE history ("
            "id TEXT PRIMARY KEY, timestamp INTEGER, duration INTEGER, "
            "exit INTEGER, command TEXT, cwd TEXT, session TEXT, "
            "hostname TEXT, deleted_at INTEGER)"
        )
        conn.execute(
            "INSERT INTO history VALUES "
            "('live', 1, 0, 0, 'ls', '/tmp', 's', 'h', NULL)"
        )
        conn.execute(
            "INSERT INTO history VALUES "
            "('gone', 2, 0, 0, 'rm -rf /', '/tmp', 's', 'h', 42)"
        )
        conn.commit()
    finally:
        conn.close()

    cmds = load_atuin(db)
    assert [c.raw for c in cmds] == ["ls"]


def test_load_atuin_skips_empty_command_rows(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    _make_atuin_db(
        db,
        [
            ("a", 1, 0, 0, "", "/tmp", None),
            ("b", 2, 0, 0, "echo hi", "/tmp", None),
        ],
    )
    cmds = load_atuin(db)
    assert [c.raw for c in cmds] == ["echo hi"]


def test_load_atuin_handles_schema_without_deleted_at(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    _make_atuin_db(
        db,
        [("a", 1, 0, 0, "ls", "/tmp", "s1")],
        include_deleted_at=False,
    )
    cmds = load_atuin(db)
    assert [c.raw for c in cmds] == ["ls"]


def test_load_atuin_gracefully_handles_non_sqlite(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-db.db"
    bogus.write_text("this is not sqlite")
    # Shouldn't raise — return empty and let the caller fall back.
    assert load_atuin(bogus) == []
