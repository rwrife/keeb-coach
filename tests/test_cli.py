"""Smoke tests for the M1 CLI."""

from __future__ import annotations

import pytest

from keeb_coach import __version__
from keeb_coach.cli import main


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


def test_score_command_runs(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["score"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Coach is warming up" in out
