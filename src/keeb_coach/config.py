"""Load + merge KeebCoach's TOML config with built-in defaults.

Config lives at ``~/.config/keeb-coach/config.toml`` (or wherever the
``XDG_CONFIG_HOME`` env var points). Everything is optional — a missing
file, a missing section, or a malformed value all fall back cleanly to
the defaults returned by :func:`default_config`.

The shape is intentionally shallow:

.. code-block:: toml

    [detectors.missing_alias]
    min_count = 4
    min_length = 8

    [detectors.slow_tool]
    min_count = 3
    [detectors.slow_tool.replacements]
    "ls -la" = "eza -la"
    "grep" = "rg"

    [detectors.long_path]
    min_count = 3
    min_depth = 3

    [detectors.sudo_redo]
    min_count = 2

Consumers get a plain ``dict[str, object]`` back and each detector
already knows how to pluck its own ``[detectors.<id>]`` sub-table.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Kept at module scope so tests can monkeypatch a single symbol.
CONFIG_FILENAME = "config.toml"
CONFIG_DIRNAME = "keeb-coach"


def default_config() -> dict[str, Any]:
    """Return a fresh dict of every default the CLI relies on.

    Detectors currently read their own defaults out of their module
    constants, so this dict mostly documents the surface. Duplicating a
    small amount of state here is deliberate: it means a user can dump
    ``keeb-coach --print-config`` (future) and see the exact knobs.
    """
    return {
        "detectors": {
            "missing_alias": {
                "min_count": 4,
                "min_length": 8,
            },
            "slow_tool": {
                "min_count": 3,
                # Note: the detector already ships a default replacements
                # map with nicely-worded reasons; we intentionally do not
                # duplicate it here so user config additions merge on top
                # instead of overriding the detector's copy.
            },
            "long_path": {
                "min_count": 3,
                "min_depth": 3,
            },
            "sudo_redo": {
                "min_count": 2,
            },
        },
    }


def default_config_path() -> Path:
    """Return the canonical config path for the current environment.

    Honors ``$XDG_CONFIG_HOME`` when set, otherwise falls back to
    ``~/.config``. We never *create* the path — that's a user decision.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / CONFIG_DIRNAME / CONFIG_FILENAME


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into a copy of ``base``.

    Overlay values win; if both sides are mappings we recurse, otherwise
    the overlay value replaces the base value outright. This mirrors how
    users expect TOML "patches" to layer on top of defaults.
    """
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load the TOML config, merging over defaults.

    Args:
        path: Explicit config path. When ``None``, uses
            :func:`default_config_path`. A non-existent or unreadable
            file returns the defaults unchanged rather than raising —
            KeebCoach should never fail hard on config.

    Returns:
        The merged config dict, always with the same shape as
        :func:`default_config`.
    """
    defaults = default_config()
    target = path if path is not None else default_config_path()
    if not target.exists():
        return defaults
    try:
        with target.open("rb") as fh:
            user = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        # Tolerate a broken file — better to grade with defaults than crash.
        return defaults
    if not isinstance(user, Mapping):
        return defaults
    return _deep_merge(defaults, user)
