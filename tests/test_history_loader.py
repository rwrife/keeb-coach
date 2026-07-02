"""Tests for shell history detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from keeb_coach.history import loader


def test_detect_shell_bash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    assert loader.detect_shell() == "bash"


def test_detect_shell_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/opt/weird/xonsh")
    assert loader.detect_shell() == "unknown"


def test_find_history_uses_histfile_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "custom_history"
    fake.write_text("echo hi\n")
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(fake))
    src = loader.find_history()
    assert src.shell == "bash"
    assert src.path == fake
    assert src.exists is True


def test_find_history_missing_returns_primary_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HISTFILE", raising=False)
    src = loader.find_history()
    assert src.shell == "bash"
    assert src.exists is False
    assert src.path.name == ".bash_history"
