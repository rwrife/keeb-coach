"""Local SQLite store of scorecard runs over time.

KeebCoach is local-first: this module is the only thing that ever
touches persistent state. It records one row per ``score`` invocation
so that later runs (and the ``trend`` command) can show progress —
"you cut retyped paths 60% this week 💪" and friends.

Design constraints:

- **Stdlib only.** ``sqlite3`` ships with CPython. We add zero deps.
- **Local, single-user.** The DB lives under ``$XDG_DATA_HOME`` (or
  ``~/.local/share``). No network, no sync, no daemon.
- **Never fails hard on I/O.** A missing parent dir gets created on
  demand; a locked or corrupted DB should degrade to "no trend data"
  in the CLI rather than crashing the scorecard.
- **Opt-outable.** ``score --no-record`` skips the write, and callers
  can point ``--db`` anywhere (tests use ``tmp_path``).

Schema (v1):

.. code-block:: sql

    CREATE TABLE runs (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts           TEXT    NOT NULL,   -- ISO-8601 UTC (Z-suffixed)
        shell        TEXT    NOT NULL,
        history_path TEXT    NOT NULL,
        days         INTEGER NOT NULL,
        total_commands INTEGER NOT NULL,
        score        INTEGER NOT NULL,
        grade        TEXT    NOT NULL
    );

    CREATE TABLE finding_counts (
        run_id   INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        detector TEXT    NOT NULL,
        count    INTEGER NOT NULL,
        PRIMARY KEY (run_id, detector)
    );

Additive-only migrations: bump ``SCHEMA_VERSION`` and register another
step in ``_MIGRATIONS`` — never rewrite an existing step in place.
"""

from __future__ import annotations

import os
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .scoring import Scorecard

DATA_DIRNAME = "keeb-coach"
DB_FILENAME = "history.db"

# Bump when adding a migration step. Each step is idempotent and
# additive — never mutate an existing step, always append a new one.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunRecord:
    """One recorded ``score`` invocation.

    Timestamp is stored as ISO-8601 UTC with trailing ``Z`` and exposed
    here as an aware :class:`~datetime.datetime`. ``findings`` is the
    per-detector count map (empty dict = clean sheet).
    """

    id: int
    ts: datetime
    shell: str
    history_path: str
    days: int
    total_commands: int
    score: int
    grade: str
    findings: dict[str, int]


@dataclass(frozen=True)
class TrendDelta:
    """A comparison of the latest run against a reference window.

    ``window_days`` is what we asked for (e.g. 7); ``reference_run`` is
    the actual run that anchored the comparison — usually the newest
    run older than the window, so "this week vs last week" always
    compares to *a real prior run* even when the user runs KeebCoach
    sporadically.
    """

    window_days: int
    latest: RunRecord
    reference_run: RunRecord | None
    score_delta: int  # latest.score - reference.score
    findings_delta: dict[str, int]  # detector -> latest - reference (int)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def default_db_path() -> Path:
    """Return the canonical DB path.

    Honors ``$XDG_DATA_HOME`` when set, otherwise falls back to
    ``~/.local/share``. The directory is *not* created here — writers
    create it lazily so read-only callers stay side-effect free.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / DATA_DIRNAME / DB_FILENAME


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------


def _connect(path: Path) -> sqlite3.Connection:
    """Open a connection with foreign keys on and a short busy timeout.

    ``detect_types`` is deliberately off — we store timestamps as text
    so the on-disk format is portable and human-readable. We use the
    stdlib default deferred-transaction mode so ``with conn:`` gives us
    proper commit/rollback semantics.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=2.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _current_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Bring the DB up to :data:`SCHEMA_VERSION`.

    Each migration is guarded by ``user_version`` so re-running is a
    no-op. All statements run inside one ``with conn:`` block so a
    crash mid-migration leaves the DB at the prior version.
    """
    current = _current_user_version(conn)
    if current >= SCHEMA_VERSION:
        return
    with conn:
        if current < 1:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts             TEXT    NOT NULL,
                    shell          TEXT    NOT NULL,
                    history_path   TEXT    NOT NULL,
                    days           INTEGER NOT NULL,
                    total_commands INTEGER NOT NULL,
                    score          INTEGER NOT NULL,
                    grade          TEXT    NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts);

                CREATE TABLE IF NOT EXISTS finding_counts (
                    run_id   INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    detector TEXT    NOT NULL,
                    count    INTEGER NOT NULL,
                    PRIMARY KEY (run_id, detector)
                );
                """
            )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


@contextmanager
def _open(path: Path) -> Iterator[sqlite3.Connection]:
    """Context-managed connection with migrations already applied."""
    conn = _connect(path)
    try:
        _apply_migrations(conn)
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC ``YYYY-MM-DDTHH:MM:SSZ`` — same format we parse back."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(raw: str) -> datetime:
    """Parse the timestamps we wrote. Falls back to fromisoformat."""
    # We always write with the trailing Z. ``fromisoformat`` in 3.11+
    # handles it directly, but older text (e.g. hand-edited) might use
    # a ``+00:00`` offset — support both.
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        # Last-ditch: assume naive UTC and attach tzinfo.
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)


def _counts_from_scorecard(scorecard: Scorecard) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for finding in scorecard.findings:
        counter[finding.detector] += 1
    return dict(counter)


def record_run(
    scorecard: Scorecard,
    *,
    shell: str,
    history_path: str | Path,
    days: int,
    db_path: Path | None = None,
    ts: datetime | None = None,
) -> RunRecord:
    """Persist a scorecard as a new row in the ``runs`` table.

    Args:
        scorecard: The just-computed scorecard.
        shell: Detected shell name (``bash``, ``zsh``, …).
        history_path: Source history file — recorded for provenance.
        days: The ``--days`` window that produced this run.
        db_path: Explicit DB path; defaults to :func:`default_db_path`.
        ts: Override the timestamp (tests use this to control ordering).

    Returns:
        The inserted :class:`RunRecord`, with the assigned ``id``.
    """
    target = db_path if db_path is not None else default_db_path()
    stamp = (
        ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if ts is not None
        else _now_iso()
    )
    counts = _counts_from_scorecard(scorecard)
    with _open(target) as conn, conn, closing(conn.cursor()) as cur:
        cur.execute(
            "INSERT INTO runs (ts, shell, history_path, days, "
            "total_commands, score, grade) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                stamp,
                shell,
                str(history_path),
                int(days),
                int(scorecard.total_commands),
                int(scorecard.score),
                scorecard.grade,
            ),
        )
        run_id = int(cur.lastrowid or 0)
        if counts:
            cur.executemany(
                "INSERT INTO finding_counts (run_id, detector, count) "
                "VALUES (?, ?, ?)",
                [(run_id, det, count) for det, count in counts.items()],
            )
    return RunRecord(
        id=run_id,
        ts=_parse_ts(stamp),
        shell=shell,
        history_path=str(history_path),
        days=int(days),
        total_commands=int(scorecard.total_commands),
        score=int(scorecard.score),
        grade=scorecard.grade,
        findings=counts,
    )


def _hydrate_runs(
    conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]
) -> list[RunRecord]:
    """Attach ``finding_counts`` to each row and build ``RunRecord``s."""
    if not rows:
        return []
    ids = [int(row["id"]) for row in rows]
    placeholders = ",".join("?" for _ in ids)
    counts_by_run: dict[int, dict[str, int]] = {rid: {} for rid in ids}
    for detector_row in conn.execute(
        f"SELECT run_id, detector, count FROM finding_counts "
        f"WHERE run_id IN ({placeholders})",
        ids,
    ):
        counts_by_run[int(detector_row["run_id"])][
            str(detector_row["detector"])
        ] = int(detector_row["count"])
    return [
        RunRecord(
            id=int(row["id"]),
            ts=_parse_ts(str(row["ts"])),
            shell=str(row["shell"]),
            history_path=str(row["history_path"]),
            days=int(row["days"]),
            total_commands=int(row["total_commands"]),
            score=int(row["score"]),
            grade=str(row["grade"]),
            findings=counts_by_run.get(int(row["id"]), {}),
        )
        for row in rows
    ]


def recent_runs(limit: int = 30, *, db_path: Path | None = None) -> list[RunRecord]:
    """Return the most recent runs, newest first (up to ``limit``).

    If the DB is missing or unreadable, returns an empty list — the
    caller can then render a "no history yet" note.
    """
    target = db_path if db_path is not None else default_db_path()
    if not target.exists():
        return []
    try:
        with _open(target) as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY ts DESC, id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            return _hydrate_runs(conn, rows)
    except sqlite3.DatabaseError:
        return []


def latest_run(*, db_path: Path | None = None) -> RunRecord | None:
    """Return the newest run, or ``None`` when there's no history yet."""
    runs = recent_runs(limit=1, db_path=db_path)
    return runs[0] if runs else None


def _reference_for_window(
    all_runs: Sequence[RunRecord], latest: RunRecord, window_days: int
) -> RunRecord | None:
    """Pick a reference run for a ``window_days`` comparison.

    We want the newest run *older than* ``latest.ts - window_days`` so
    that comparing "this week" against "last week" still works when the
    user runs KeebCoach only occasionally. If nothing is old enough, we
    fall back to the oldest run available — better a stale delta than
    no delta at all.
    """
    if window_days <= 0 or len(all_runs) < 2:
        return None
    cutoff = latest.ts - timedelta(days=window_days)
    # ``all_runs`` is newest-first; scan for the first entry older than cutoff.
    older = [r for r in all_runs if r.id != latest.id and r.ts <= cutoff]
    if older:
        return older[0]
    # Fallback: oldest available prior run.
    prior = [r for r in all_runs if r.id != latest.id]
    return prior[-1] if prior else None


def trend_delta(
    window_days: int = 7,
    *,
    db_path: Path | None = None,
) -> TrendDelta | None:
    """Compute the delta of the latest run against a prior reference run.

    Returns ``None`` when there is no latest run or nothing to compare
    against — callers should treat that as "no delta to show yet."
    """
    runs = recent_runs(limit=200, db_path=db_path)
    if not runs:
        return None
    latest = runs[0]
    reference = _reference_for_window(runs, latest, window_days)
    if reference is None:
        return TrendDelta(
            window_days=window_days,
            latest=latest,
            reference_run=None,
            score_delta=0,
            findings_delta={},
        )
    detectors: set[str] = set(latest.findings) | set(reference.findings)
    findings_delta = {
        det: latest.findings.get(det, 0) - reference.findings.get(det, 0)
        for det in sorted(detectors)
    }
    return TrendDelta(
        window_days=window_days,
        latest=latest,
        reference_run=reference,
        score_delta=latest.score - reference.score,
        findings_delta=findings_delta,
    )


def format_delta_headline(delta: TrendDelta | None) -> str | None:
    """Build the one-line "you cut retyped paths 60% this week 💪" copy.

    Returns ``None`` when there's not enough data (or the deltas are
    trivial). The rule: prefer the *biggest improvement* in a specific
    detector; fall back to the overall score change when everything is
    flat.
    """
    if delta is None or delta.reference_run is None:
        return None

    # Prefer the finding with the biggest percentage-cut. We only shout
    # about cuts (negative deltas); regressions get a gentler headline.
    improvements: list[tuple[str, int, int, int]] = []  # detector, before, after, delta
    regressions: list[tuple[str, int, int, int]] = []
    for detector, diff in delta.findings_delta.items():
        before = delta.reference_run.findings.get(detector, 0)
        after = delta.latest.findings.get(detector, 0)
        if before == 0 and after == 0:
            continue
        if diff < 0 and before > 0:
            improvements.append((detector, before, after, diff))
        elif diff > 0:
            regressions.append((detector, before, after, diff))

    week = delta.window_days

    def _detector_label(name: str) -> str:
        return name.replace("_", " ")

    if improvements:
        # Biggest percentage cut wins; ties break on absolute delta.
        improvements.sort(
            key=lambda row: (-((row[1] - row[2]) / row[1]), row[3])
        )
        det, before, after, diff = improvements[0]
        pct = int(round((before - after) / before * 100))
        return (
            f"You cut {_detector_label(det)} findings {pct}% "
            f"this {_window_word(week)} 💪 ({before} → {after})"
        )

    if delta.score_delta > 0:
        return (
            f"Score up {delta.score_delta} points this {_window_word(week)} "
            f"({delta.reference_run.score} → {delta.latest.score}) 📈"
        )
    if delta.score_delta < 0:
        # Softer copy for regressions — coach is grumpy, not cruel.
        return (
            f"Score slipped {abs(delta.score_delta)} points this "
            f"{_window_word(week)} ({delta.reference_run.score} → "
            f"{delta.latest.score}). Coach believes in you."
        )
    if regressions:
        det, before, after, diff = max(regressions, key=lambda row: row[3])
        return (
            f"{_detector_label(det)} findings up {diff} this "
            f"{_window_word(week)} ({before} → {after}). Hmm."
        )
    return None


def _window_word(days: int) -> str:
    """Pretty-print a windowed comparison ('week', 'day', '3 days')."""
    if days == 7:
        return "week"
    if days == 1:
        return "day"
    if days == 30:
        return "month"
    return f"{days} days"


def score_series(runs: Iterable[RunRecord]) -> list[int]:
    """Return chronologically-ordered scores for sparkline rendering."""
    return [r.score for r in sorted(runs, key=lambda r: r.ts)]


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: Sequence[int]) -> str:
    """Render a small unicode sparkline for a series of scores.

    Handles the flat-series case (all identical values) by returning a
    row of mid-height blocks so the CLI still shows *something*.
    """
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        mid = _SPARK_CHARS[len(_SPARK_CHARS) // 2]
        return mid * len(values)
    span = hi - lo
    n = len(_SPARK_CHARS) - 1
    return "".join(
        _SPARK_CHARS[int(round((v - lo) / span * n))] for v in values
    )
