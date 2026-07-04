"""Tests for the TOML config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from keeb_coach.config import (
    default_config,
    default_config_path,
    load_config,
)


def test_default_config_has_expected_shape() -> None:
    cfg = default_config()
    assert "detectors" in cfg
    for detector_id in ("missing_alias", "slow_tool", "long_path", "sudo_redo"):
        assert detector_id in cfg["detectors"], detector_id


def test_default_config_returns_a_copy_each_call() -> None:
    # Mutating the returned dict must not poison future calls.
    a = default_config()
    a["detectors"]["missing_alias"]["min_count"] = 999
    b = default_config()
    assert b["detectors"]["missing_alias"]["min_count"] != 999


def test_default_path_uses_xdg_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    p = default_config_path()
    assert p == tmp_path / "keeb-coach" / "config.toml"


def test_default_path_falls_back_to_home_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    p = default_config_path()
    assert p == tmp_path / ".config" / "keeb-coach" / "config.toml"


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"
    assert load_config(missing) == default_config()


def test_load_merges_user_overrides(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        """
        [detectors.missing_alias]
        min_count = 10

        [detectors.slow_tool.replacements]
        "grep" = "ugrep"
        "top" = "btop"
        """.strip()
    )
    cfg = load_config(p)
    assert cfg["detectors"]["missing_alias"]["min_count"] == 10
    # Default value we didn't override survives.
    assert cfg["detectors"]["missing_alias"]["min_length"] == 8
    # User replacements land in the slow_tool section unchanged;
    # the detector itself owns the built-in replacement map so we
    # do NOT duplicate it in defaults — only the user's overrides.
    replacements = cfg["detectors"]["slow_tool"]["replacements"]
    assert replacements == {"grep": "ugrep", "top": "btop"}


def test_load_ignores_broken_toml(tmp_path: Path) -> None:
    p = tmp_path / "bad.toml"
    p.write_text("this is [not valid toml === ")
    # Broken file → silently fall back to defaults.
    assert load_config(p) == default_config()


def test_load_deep_merges_nested_sections(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        """
        [detectors.long_path]
        min_depth = 5
        """.strip()
    )
    cfg = load_config(p)
    long_path = cfg["detectors"]["long_path"]
    assert long_path["min_depth"] == 5
    # Sibling default (min_count) still present after merge.
    assert long_path["min_count"] == 3


def test_load_ignores_non_mapping_top_level(tmp_path: Path) -> None:
    # TOML technically can't produce a non-mapping root, but guard anyway:
    # an empty file loads as an empty dict, which should still merge cleanly.
    p = tmp_path / "empty.toml"
    p.write_text("")
    assert load_config(p) == default_config()


def test_load_uses_default_path_when_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # No config file at the resolved path → defaults, no crash.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("HOME", raising=False)
    assert load_config(None) == default_config()
