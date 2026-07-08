"""Smoke tests for the M1 CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from keeb_coach import __version__
from keeb_coach.cli import main
from keeb_coach.detectors.base import Finding, Severity
from keeb_coach.scoring import score_findings
from keeb_coach.storage import recent_runs, record_run

FIXTURES = Path(__file__).parent / "fixtures"


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "keeb-coach" in out
    assert "score" in out


def test_score_command_missing_history(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Point HOME at an empty dir with no history files.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.delenv("HISTFILE", raising=False)
    rc = main(["score"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Coach is warming up" in out
    assert "no" in out.lower()  # "Exists: no"


def test_score_command_with_bash_fixture(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    # --days 0 disables the window so this test stays deterministic no
    # matter how far into the future the wall clock moves.
    rc = main(["score", "--days", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Total commands:" in out
    assert "15" in out  # 15 commands in the bash fixture
    # Table title reflects distinct programs; fixture has 8 unique.
    assert "commands" in out.lower()
    assert "git" in out
    # M3: the fixture has `git status` × 5 → the alias detector should fire
    # and the scorecard banner should render.
    assert "Efficiency scorecard" in out
    assert "missing_alias" in out


def test_score_command_with_zsh_fixture(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "zsh_history.txt"))
    rc = main(["score", "--days", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Total commands:" in out
    assert "15" in out
    assert "commands" in out.lower()
    assert "git" in out
    assert "Efficiency scorecard" in out
    assert "missing_alias" in out


def test_score_command_with_custom_config(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Bash fixture has `git status` × 5 — default min_count is 4 so
    # the alias detector already fires. Crank thresholds up so the
    # config actually silences it, proving the CLI wires config through.
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[detectors.missing_alias]\nmin_count = 999\nmin_length = 999\n"
        "[detectors.slow_tool]\nmin_count = 999\n"
        "[detectors.long_path]\nmin_count = 999\n"
        "[detectors.sudo_redo]\nmin_count = 999\n"
    )
    rc = main(["score", "--config", str(cfg), "--days", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    # With every threshold neutralized, no findings should surface.
    assert "Clean sheet" in out


# ---------------------------------------------------------------------------
# M5: `fixes` subcommand
# ---------------------------------------------------------------------------


def test_fixes_command_prints_snippets(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same fixture as score — the bash history has `git status` × 5
    # so we expect at least the missing_alias snippet to appear.
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    rc = main(["fixes", "--days", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    # Header advertises --write so users discover it.
    assert "--write" in out
    # The missing_alias finding for `git status` becomes an alias line.
    assert "alias git_status=" in out


def test_fixes_command_no_history(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.delenv("HISTFILE", raising=False)
    rc = main(["fixes"])
    assert rc == 0
    out = capsys.readouterr().out
    # A missing history file is a soft failure — print a note, exit 0.
    assert "nothing to fix" in out.lower() or "no history" in out.lower()


def test_fixes_write_creates_managed_block(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    target = tmp_path / ".keeb_aliases"
    rc = main(["fixes", "--write", str(target), "--days", "0"])
    assert rc == 0
    text = target.read_text(encoding="utf-8")
    assert "# >>> keeb-coach managed block >>>" in text
    assert "# <<< keeb-coach managed block <<<" in text
    assert "alias git_status=" in text


def test_fixes_write_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # DoD from PLAN.md: running twice must not duplicate entries.
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    target = tmp_path / ".keeb_aliases"
    assert main(["fixes", "--write", str(target), "--days", "0"]) == 0
    assert main(["fixes", "--write", str(target), "--days", "0"]) == 0
    text = target.read_text(encoding="utf-8")
    assert text.count("alias git_status=") == 1
    assert text.count("# >>> keeb-coach managed block >>>") == 1


def test_fixes_write_refuses_bashrc(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    rc_target = tmp_path / ".bashrc"
    rc = main(["fixes", "--write", str(rc_target)])
    assert rc == 2
    out = capsys.readouterr().out
    assert "refus" in out.lower()  # "refusing to write"
    # And the file must not have been created.
    assert not rc_target.exists()


# ---------------------------------------------------------------------------
# M6: --days window + --json output
# ---------------------------------------------------------------------------


def test_score_days_filter_narrows_window(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bash fixture timestamps are from 2024. Default --days=30 relative to
    # "now" (2026+) filters every timestamped command out; only the tail
    # of untimestamped lines survives.
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    rc = main(["score"])  # default --days 30
    assert rc == 0
    out = capsys.readouterr().out
    # 5 untimestamped tail commands remain of 15 total.
    assert "5" in out and "of 15 total" in out


def test_score_days_zero_disables_filter(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    rc = main(["score", "--days", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    # No windowing note when everything is in scope.
    assert "of 15 total" not in out
    assert "Total commands:" in out


def test_score_json_output_is_valid_and_typed(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json as _json

    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    rc = main(["score", "--json", "--days", "0"])
    assert rc == 0
    payload = _json.loads(capsys.readouterr().out)
    # Schema stability: downstream tooling depends on these keys.
    assert payload["schema"] == "keeb-coach.scorecard/v1"
    assert payload["shell"] == "bash"
    assert payload["total_commands"] == 15
    assert payload["grade"] in {"A", "B", "C", "D", "F"}
    assert isinstance(payload["score"], int) and 0 <= payload["score"] <= 100
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["top_commands"], list)
    # `git status` ×5 in the fixture → at least the alias finding.
    detectors = {f["detector"] for f in payload["findings"]}
    assert "missing_alias" in detectors
    # Severity is lowercased human string, plus a numeric rank for sorting.
    for f in payload["findings"]:
        assert f["severity"] in {"low", "medium", "high"}
        assert isinstance(f["severity_rank"], int)


def test_score_json_output_with_missing_history(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import json as _json

    # No history file → still produce valid, empty JSON so scripts don't
    # need to special-case the first-run case.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.delenv("HISTFILE", raising=False)
    rc = main(["score", "--json"])
    assert rc == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["total_commands"] == 0
    assert payload["findings"] == []
    assert payload["grade"] == "A"
    assert payload.get("note") == "history file not found"


def test_fixes_days_filter_narrows_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # `fixes --days 30` on the 2024-vintage fixture: the timestamped
    # `git status` ×5 is gone, so no missing_alias snippet should appear.
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    target = tmp_path / ".keeb_aliases"
    rc = main(["fixes", "--write", str(target)])  # default --days 30
    assert rc == 0
    text = target.read_text(encoding="utf-8")
    assert "alias git_status=" not in text


# ---------------------------------------------------------------------------
# Streak DB integration + `trend` command
# ---------------------------------------------------------------------------


def _seed_bash_run(
    monkeypatch: pytest.MonkeyPatch,
    db: Path,
) -> None:
    """Point HISTFILE at the bash fixture; caller runs `score`."""
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    # We rely on the caller passing --db to steer the write.


def test_score_records_run_to_db_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`score` should write a row into the SQLite streak DB."""
    db = tmp_path / "streak.db"
    _seed_bash_run(monkeypatch, db)
    rc = main(["score", "--days", "0", "--db", str(db)])
    assert rc == 0
    runs = recent_runs(limit=5, db_path=db)
    assert len(runs) == 1
    assert runs[0].shell == "bash"
    # bash fixture has `git status` × 5 → alias detector fires.
    assert runs[0].findings.get("missing_alias", 0) >= 1


def test_score_no_record_skips_db_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`--no-record` must not touch the streak DB."""
    db = tmp_path / "streak.db"
    _seed_bash_run(monkeypatch, db)
    rc = main(
        ["score", "--days", "0", "--db", str(db), "--no-record"]
    )
    assert rc == 0
    # DB should not exist at all — no lazy dir creation either.
    assert not db.exists()
    assert recent_runs(db_path=db) == []


def test_score_json_includes_trend_when_second_run(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A prior recorded run should show up under `trend` in JSON."""

    db = tmp_path / "streak.db"
    # Seed a prior run *older than the window* so trend_delta binds.
    prior = score_findings(
        [Finding("missing_alias", Severity.MEDIUM, "seed")] * 5,
        total_commands=200,
    )
    record_run(
        prior,
        shell="bash",
        history_path="/tmp/seed",
        days=30,
        db_path=db,
        ts=datetime.now(tz=UTC) - timedelta(days=14),
    )

    _seed_bash_run(monkeypatch, db)
    rc = main(
        ["score", "--json", "--days", "0", "--db", str(db), "--window", "7"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "trend" in payload
    trend = payload["trend"]
    assert trend["window_days"] == 7
    assert trend["reference"] is not None
    # We had 5 alias findings before, at most 1 now → biggest cut wins.
    assert isinstance(trend["findings_delta"], dict)
    assert trend["headline"]


def test_trend_command_empty_when_no_db(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    rc = main(["trend", "--db", str(tmp_path / "nope.db")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No streak history yet" in out


def test_trend_command_shows_recent_runs(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:

    db = tmp_path / "streak.db"
    now = datetime.now(tz=UTC)
    for offset in (10, 3, 0):
        sc = score_findings(
            [Finding("long_path", Severity.LOW, "seed")] * offset,
            total_commands=100,
        )
        record_run(
            sc,
            shell="zsh",
            history_path="/tmp/x",
            days=30,
            db_path=db,
            ts=now - timedelta(days=offset),
        )

    rc = main(["trend", "--db", str(db), "--window", "7"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "keeb-coach trend" in out
    assert "3 recorded run(s)" in out
    # Table should list the detector column.
    assert "long_path" in out
    # Sparkline + a delta panel comparing to the run outside the window.
    assert "vs. 7d ago" in out


def test_trend_command_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:

    db = tmp_path / "streak.db"
    record_run(
        score_findings([], total_commands=42),
        shell="bash",
        history_path="/tmp/x",
        days=30,
        db_path=db,
    )
    rc = main(["trend", "--db", str(db), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "keeb-coach.trend/v1"
    assert isinstance(payload["runs"], list) and len(payload["runs"]) == 1
    assert payload["runs"][0]["shell"] == "bash"
    assert payload["runs"][0]["total_commands"] == 42
