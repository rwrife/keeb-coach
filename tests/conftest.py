"""Session-wide pytest fixtures.

The main job here is to keep KeebCoach tests hermetic:

- ``score`` writes to a SQLite streak DB by default. We redirect
  ``$XDG_DATA_HOME`` to a temp directory per test so that running
  ``pytest`` locally never touches the developer's real
  ``~/.local/share/keeb-coach/history.db``.
- Same story for config: ``$XDG_CONFIG_HOME`` is pinned so a stray
  personal ``config.toml`` can't influence detector thresholds during
  tests. Individual tests can still monkeypatch these back to
  something specific.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_xdg_dirs(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirect XDG data + config dirs to a fresh temp dir per test.

    ``autouse=True`` so no individual test has to remember. Tests that
    need to point somewhere else can still override with their own
    ``monkeypatch.setenv``.
    """
    data_dir: Path = tmp_path_factory.mktemp("xdg-data")
    config_dir: Path = tmp_path_factory.mktemp("xdg-config")
    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
