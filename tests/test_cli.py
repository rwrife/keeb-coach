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
    assert "Top 10 commands" in out
    assert "git" in out


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
    assert "Top 10 commands" in out
    assert "git" in out
