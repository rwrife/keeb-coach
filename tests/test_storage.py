"""Tests for the SQLite-backed streak store."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from keeb_coach.detectors.base import Finding, Severity
from keeb_coach.scoring import score_findings
from keeb_coach.storage import (
    SCHEMA_VERSION,
    default_db_path,
    format_delta_headline,
    latest_run,
    recent_runs,
    record_run,
    score_series,
    sparkline,
    trend_delta,
)


def _finding(detector: str, severity: Severity = Severity.LOW) -> Finding:
    return Finding(
        detector=detector,
        severity=severity,
        message=f"{detector} says hi",
    )


def _make_scorecard(**counts: int):
    """Build a scorecard whose per-detector count matches ``counts``.

    Severity is fixed to LOW so callers don't have to think about the
    penalty math when they just want a specific finding shape.
    """
    findings = []
    for detector, n in counts.items():
        for _ in range(n):
            findings.append(_finding(detector))
    return score_findings(findings, total_commands=100)


# ---------------------------------------------------------------------------
# default_db_path
# ---------------------------------------------------------------------------


def test_default_db_path_uses_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_db_path() == tmp_path / "keeb-coach" / "history.db"


def test_default_db_path_falls_back_to_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert (
        default_db_path()
        == tmp_path / ".local" / "share" / "keeb-coach" / "history.db"
    )


# ---------------------------------------------------------------------------
# record_run + schema
# ---------------------------------------------------------------------------


def test_record_run_creates_db_and_persists_row(tmp_path: Path) -> None:
    db = tmp_path / "streak.db"
    scorecard = _make_scorecard(missing_alias=2, slow_tool=1)
    rec = record_run(
        scorecard,
        shell="zsh",
        history_path="/home/dev/.zsh_history",
        days=30,
        db_path=db,
    )

    assert db.exists()
    assert rec.id > 0
    assert rec.grade == scorecard.grade
    assert rec.findings == {"missing_alias": 2, "slow_tool": 1}

    # Row should round-trip.
    fetched = latest_run(db_path=db)
    assert fetched is not None
    assert fetched.id == rec.id
    assert fetched.score == scorecard.score
    assert fetched.findings == rec.findings


def test_record_run_schema_version_is_pinned(tmp_path: Path) -> None:
    db = tmp_path / "streak.db"
    record_run(
        _make_scorecard(),
        shell="bash",
        history_path="/tmp/history",
        days=7,
        db_path=db,
    )
    with sqlite3.connect(str(db)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_record_run_ts_override_persists(tmp_path: Path) -> None:
    """Explicit ``ts=`` lets tests control ordering deterministically."""
    db = tmp_path / "streak.db"
    fixed = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    rec = record_run(
        _make_scorecard(),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=fixed,
    )
    assert rec.ts == fixed
    fetched = latest_run(db_path=db)
    assert fetched is not None
    assert fetched.ts == fixed


def test_recent_runs_orders_newest_first(tmp_path: Path) -> None:
    db = tmp_path / "streak.db"
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    for offset in range(5):
        record_run(
            _make_scorecard(missing_alias=offset),
            shell="bash",
            history_path="/tmp/x",
            days=30,
            db_path=db,
            ts=t0 + timedelta(days=offset),
        )
    runs = recent_runs(limit=10, db_path=db)
    assert [r.ts for r in runs] == list(
        reversed([t0 + timedelta(days=i) for i in range(5)])
    )
    assert runs[0].findings == {"missing_alias": 4}


def test_recent_runs_empty_on_missing_db(tmp_path: Path) -> None:
    assert recent_runs(db_path=tmp_path / "nope.db") == []
    assert latest_run(db_path=tmp_path / "nope.db") is None


def test_recent_runs_empty_on_corrupt_db(tmp_path: Path) -> None:
    """A garbage file should degrade to 'no data', not blow up the CLI."""
    db = tmp_path / "streak.db"
    db.write_bytes(b"this is not a sqlite file")
    assert recent_runs(db_path=db) == []


# ---------------------------------------------------------------------------
# trend_delta
# ---------------------------------------------------------------------------


def test_trend_delta_none_when_no_runs(tmp_path: Path) -> None:
    assert trend_delta(db_path=tmp_path / "nope.db") is None


def test_trend_delta_single_run_has_no_reference(tmp_path: Path) -> None:
    db = tmp_path / "streak.db"
    record_run(
        _make_scorecard(missing_alias=1),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
    )
    delta = trend_delta(db_path=db)
    assert delta is not None
    assert delta.reference_run is None
    assert delta.score_delta == 0


def test_trend_delta_picks_reference_older_than_window(tmp_path: Path) -> None:
    db = tmp_path / "streak.db"
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

    # Old baseline: 8 days ago, heavy findings.
    record_run(
        _make_scorecard(long_path=5, missing_alias=2),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now - timedelta(days=8),
    )
    # In-window run 3 days ago should NOT be chosen as reference.
    record_run(
        _make_scorecard(long_path=4, missing_alias=1),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now - timedelta(days=3),
    )
    # Latest: much better.
    record_run(
        _make_scorecard(long_path=2, missing_alias=1),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now,
    )

    delta = trend_delta(window_days=7, db_path=db)
    assert delta is not None
    assert delta.reference_run is not None
    # Reference is the 8-day-old run, not the 3-day-old one.
    assert delta.reference_run.ts == now - timedelta(days=8)
    assert delta.findings_delta == {"long_path": -3, "missing_alias": -1}


def test_trend_delta_falls_back_to_oldest_prior_when_none_outside_window(
    tmp_path: Path,
) -> None:
    """Two recent runs, both inside the window: still show *something*."""
    db = tmp_path / "streak.db"
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    record_run(
        _make_scorecard(missing_alias=3),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now - timedelta(days=1),
    )
    record_run(
        _make_scorecard(missing_alias=1),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now,
    )
    delta = trend_delta(window_days=30, db_path=db)
    assert delta is not None
    assert delta.reference_run is not None
    assert delta.findings_delta == {"missing_alias": -2}


# ---------------------------------------------------------------------------
# format_delta_headline
# ---------------------------------------------------------------------------


def test_format_delta_headline_prefers_biggest_cut(tmp_path: Path) -> None:
    db = tmp_path / "streak.db"
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    # Reference: 5 long_path, 4 missing_alias.
    record_run(
        _make_scorecard(long_path=5, missing_alias=4),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now - timedelta(days=10),
    )
    # Latest: cut long_path in half, cut missing_alias by one.
    record_run(
        _make_scorecard(long_path=2, missing_alias=3),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now,
    )
    delta = trend_delta(window_days=7, db_path=db)
    headline = format_delta_headline(delta)
    assert headline is not None
    # 60% cut on long_path beats 25% cut on missing_alias.
    assert "long path" in headline
    assert "60%" in headline
    assert "💪" in headline


def test_format_delta_headline_returns_none_when_flat(tmp_path: Path) -> None:
    db = tmp_path / "streak.db"
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    for offset in (10, 0):
        record_run(
            _make_scorecard(missing_alias=2),
            shell="bash",
            history_path="/tmp/x",
            days=30,
            db_path=db,
            ts=now - timedelta(days=offset),
        )
    delta = trend_delta(window_days=7, db_path=db)
    assert format_delta_headline(delta) is None


def test_format_delta_headline_regression_is_gentle(tmp_path: Path) -> None:
    db = tmp_path / "streak.db"
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    # Reference: clean. Latest: worse.
    record_run(
        _make_scorecard(),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now - timedelta(days=10),
    )
    record_run(
        _make_scorecard(missing_alias=3),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
        ts=now,
    )
    delta = trend_delta(window_days=7, db_path=db)
    headline = format_delta_headline(delta)
    assert headline is not None
    # We got worse — either the "score slipped" or the fallback "hmm" copy.
    assert "slipped" in headline or "Hmm" in headline


# ---------------------------------------------------------------------------
# sparkline / score_series
# ---------------------------------------------------------------------------


def test_sparkline_empty_returns_empty_string() -> None:
    assert sparkline([]) == ""


def test_sparkline_flat_series_shows_mid_bar() -> None:
    out = sparkline([50, 50, 50])
    assert len(out) == 3
    assert len(set(out)) == 1  # all identical


def test_sparkline_uses_full_range() -> None:
    out = sparkline([0, 50, 100])
    # Endpoints hit the min and max characters.
    assert out[0] == "▁"
    assert out[-1] == "█"


def test_score_series_is_chronological(tmp_path: Path) -> None:
    """``score_series`` sorts oldest-first regardless of input order."""
    db = tmp_path / "streak.db"
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    for offset, s in [(0, 90), (2, 70), (1, 80)]:
        record_run(
            _make_scorecard(missing_alias=(100 - s) // 3),
            shell="bash",
            history_path="/tmp/x",
            days=30,
            db_path=db,
            ts=now - timedelta(days=offset),
        )
    runs = recent_runs(limit=10, db_path=db)
    assert score_series(runs) == [
        r.score for r in sorted(runs, key=lambda r: r.ts)
    ]
