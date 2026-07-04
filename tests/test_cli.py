"""Smoke tests for the M1 CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from keeb_coach import __version__
from keeb_coach.cli import main

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
    rc = main(["score"])
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
    rc = main(["score"])
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
    rc = main(["score", "--config", str(cfg)])
    assert rc == 0
    out = capsys.readouterr().out
    # With every threshold neutralized, no findings should surface.
    assert "Clean sheet" in out
