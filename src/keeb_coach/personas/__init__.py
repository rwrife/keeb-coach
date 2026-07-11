"""Swappable coach personas.

A **persona** is just a bundle of roast copy: one line per
``(detector, severity)`` slot, plus a couple of banner strings
(``clean_sheet``, ``takes_header``). Personas are pure data — each one
lives in its own ``data/<id>.toml`` file, so adding "Surfer Bro" or
"Shakespeare" is a one-file change with zero Python.

The default persona reproduces the original roast copy verbatim so
nothing about the M4 output changes when ``--persona`` is omitted.

TOML shape (see ``data/default.toml`` for the canonical example):

.. code-block:: toml

    id = "drill_sergeant"
    name = "Drill Sergeant"
    description = "Barks. A lot."

    [strings]
    takes_header = "Coach's take:"
    clean_sheet = "No slack found, soldier. Dismissed."

    [roasts.missing_alias]
    low  = "Sloppy. Alias it."
    med  = "Alias. It. Now."
    high = "DROP AND GIVE ME AN ALIAS."

Missing detector entries fall through to the default persona — a
persona file only has to override what it cares about.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from ..detectors.base import Finding, Severity

# Order matters: the *first* persona listed here is treated as the
# built-in default and is used as the fallback for missing roast slots.
_BUILTIN_IDS: tuple[str, ...] = (
    "default",
    "drill_sergeant",
    "zen_master",
    "passive_aggressive_pm",
)

_SEVERITY_KEYS: dict[Severity, tuple[str, ...]] = {
    # Accept both short and long forms in TOML so persona authors can
    # write whichever reads better in context.
    Severity.LOW: ("low",),
    Severity.MEDIUM: ("med", "medium"),
    Severity.HIGH: ("high",),
}


class PersonaError(ValueError):
    """Raised when a persona id can't be resolved."""


@dataclass(frozen=True)
class Persona:
    """One coach voice.

    Attributes:
        id: Stable slug (``drill_sergeant``, ``zen_master``, ...).
        name: Human display name for headers/help text.
        description: One-line pitch; shown in ``--help`` listings.
        roasts: ``{detector_id: {Severity: line}}`` — sparse; any
            missing slot falls back to the default persona.
        strings: Named UI strings (``takes_header``, ``clean_sheet``).
            Sparse; missing keys fall back to the default persona.
    """

    id: str
    name: str
    description: str = ""
    roasts: dict[str, dict[Severity, str]] = field(default_factory=dict)
    strings: dict[str, str] = field(default_factory=dict)

    def roast_for(self, finding: Finding, *, fallback: Persona | None = None) -> str | None:
        """Return the roast line for this ``finding``.

        Falls back to ``fallback`` (typically the default persona) when
        this persona doesn't override the ``(detector, severity)``
        slot. Returns ``None`` when no persona has a line at all —
        callers should treat that as "skip this row."
        """
        line = self.roasts.get(finding.detector, {}).get(finding.severity)
        if line is not None:
            return line
        if fallback is not None and fallback is not self:
            return fallback.roast_for(finding, fallback=None)
        return None

    def string(self, key: str, *, fallback: Persona | None = None, default: str = "") -> str:
        """Return a named UI string (``takes_header``, ``clean_sheet``, ...).

        Same fallback semantics as :meth:`roast_for`.
        """
        value = self.strings.get(key)
        if value is not None:
            return value
        if fallback is not None and fallback is not self:
            return fallback.string(key, fallback=None, default=default)
        return default


def _parse_roasts(raw: Mapping[str, Any]) -> dict[str, dict[Severity, str]]:
    """Convert a TOML ``[roasts.<detector>]`` table to typed dicts."""
    out: dict[str, dict[Severity, str]] = {}
    for detector, table in raw.items():
        if not isinstance(table, Mapping):
            continue
        by_sev: dict[Severity, str] = {}
        for sev, keys in _SEVERITY_KEYS.items():
            for key in keys:
                value = table.get(key)
                if isinstance(value, str) and value:
                    by_sev[sev] = value
                    break
        if by_sev:
            out[detector] = by_sev
    return out


def _persona_from_toml(data: Mapping[str, Any], *, source: str) -> Persona:
    """Build a :class:`Persona` from a parsed TOML mapping."""
    pid = data.get("id")
    if not isinstance(pid, str) or not pid:
        raise PersonaError(f"persona {source!r}: missing string field 'id'")
    name = data.get("name")
    if not isinstance(name, str) or not name:
        # Fall back to a title-cased id so a minimal persona file still works.
        name = pid.replace("_", " ").title()
    description = data.get("description", "")
    if not isinstance(description, str):
        description = ""

    raw_roasts = data.get("roasts", {})
    roasts = _parse_roasts(raw_roasts) if isinstance(raw_roasts, Mapping) else {}

    raw_strings = data.get("strings", {})
    strings: dict[str, str] = {}
    if isinstance(raw_strings, Mapping):
        for key, value in raw_strings.items():
            if isinstance(value, str):
                strings[key] = value

    return Persona(
        id=pid, name=name, description=description, roasts=roasts, strings=strings
    )


def _load_builtin(pid: str) -> Persona:
    """Load a shipped persona from the ``data`` package resource."""
    pkg = resources.files(__package__) / "data"
    target = pkg / f"{pid}.toml"
    with target.open("rb") as fh:  # type: ignore[union-attr]
        data = tomllib.load(fh)
    return _persona_from_toml(data, source=f"builtin:{pid}")


def _load_from_path(path: Path) -> Persona:
    """Load a persona from an arbitrary TOML file on disk."""
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return _persona_from_toml(data, source=str(path))


def builtin_ids() -> tuple[str, ...]:
    """Return the shipped persona ids, default first."""
    return _BUILTIN_IDS


def default_persona() -> Persona:
    """Return the default (fallback) persona.

    Cached implicitly by the caller if needed — this is cheap enough
    that a fresh load per call is fine and avoids surprising test
    pollution across ``importlib.resources`` invalidation.
    """
    return _load_builtin(_BUILTIN_IDS[0])


def load_all_builtins() -> list[Persona]:
    """Load every shipped persona (for ``--help`` listings, docs, etc.)."""
    return [_load_builtin(pid) for pid in _BUILTIN_IDS]


def iter_persona_files(extra_dir: Path | None) -> Iterator[tuple[str, Path]]:
    """Yield ``(id, path)`` for user-supplied persona files in ``extra_dir``."""
    if extra_dir is None or not extra_dir.exists() or not extra_dir.is_dir():
        return
    for entry in sorted(extra_dir.iterdir()):
        if entry.is_file() and entry.suffix == ".toml":
            yield entry.stem, entry


def resolve_persona(
    name: str | None,
    *,
    extra_dir: Path | None = None,
) -> Persona:
    """Resolve a persona by id, path, or fall back to the default.

    Resolution order:

    1. ``None`` or empty string → default persona.
    2. ``name`` is an existing file path → load that file.
    3. ``name`` matches a ``*.toml`` file in ``extra_dir`` → load it.
    4. ``name`` matches a shipped builtin id → load it.
    5. Otherwise → :class:`PersonaError`.

    Paths take precedence over ids so a user can drop
    ``./my_coach.toml`` and pass ``--persona ./my_coach.toml`` without
    worrying about collisions with builtin names.
    """
    if not name:
        return default_persona()

    as_path = Path(name)
    if as_path.exists() and as_path.is_file():
        return _load_from_path(as_path)

    if extra_dir is not None:
        for pid, path in iter_persona_files(extra_dir):
            if pid == name:
                return _load_from_path(path)

    if name in _BUILTIN_IDS:
        return _load_builtin(name)

    available = list(_BUILTIN_IDS)
    if extra_dir is not None:
        available.extend(pid for pid, _ in iter_persona_files(extra_dir))
    raise PersonaError(
        f"unknown persona {name!r}. Available: {', '.join(sorted(set(available)))}"
    )


def persona_from_config(config: Mapping[str, Any] | None) -> str | None:
    """Extract the configured persona id from a merged config dict.

    Looks at ``[coach] persona`` (preferred) and falls back to
    ``[personas] default`` for people who think of it as a persona
    setting. Returns ``None`` when nothing is configured.
    """
    if not config:
        return None
    coach = config.get("coach")
    if isinstance(coach, Mapping):
        value = coach.get("persona")
        if isinstance(value, str) and value:
            return value
    personas = config.get("personas")
    if isinstance(personas, Mapping):
        value = personas.get("default")
        if isinstance(value, str) and value:
            return value
    return None


def persona_dir_from_config(config: Mapping[str, Any] | None) -> Path | None:
    """Extract ``[coach] persona_dir`` from config (optional user dir)."""
    if not config:
        return None
    coach = config.get("coach")
    if isinstance(coach, Mapping):
        value = coach.get("persona_dir")
        if isinstance(value, str) and value:
            return Path(value).expanduser()
    return None
