"""Tests for the swappable coach personas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from keeb_coach.cli import main
from keeb_coach.detectors.base import Finding, Severity
from keeb_coach.personas import (
    PersonaError,
    default_persona,
    load_all_builtins,
    persona_dir_from_config,
    persona_from_config,
    resolve_persona,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_builtin_personas_load_and_cover_core_detectors() -> None:
    personas = load_all_builtins()
    ids = {p.id for p in personas}
    assert {"default", "drill_sergeant", "zen_master", "passive_aggressive_pm"} <= ids
    core = {"missing_alias", "slow_tool", "long_path", "sudo_redo", "failed_retype"}
    for persona in personas:
        assert core <= persona.roasts.keys(), (
            f"{persona.id} missing detectors: {core - persona.roasts.keys()}"
        )
        for detector, sev_map in persona.roasts.items():
            assert sev_map, f"{persona.id}/{detector} has no severity lines"
            for line in sev_map.values():
                assert isinstance(line, str) and line.strip()


def test_default_persona_reproduces_original_copy() -> None:
    persona = default_persona()
    finding = Finding(
        detector="missing_alias", severity=Severity.HIGH, message="x"
    )
    line = persona.roast_for(finding)
    assert line == "You have hands. Use them for something new. Alias it."


def test_persona_fallback_to_default_for_missing_slot(tmp_path: Path) -> None:
    minimal = tmp_path / "minimal.toml"
    minimal.write_text(
        'id = "minimal"\nname = "Minimal"\n'
        '[roasts.missing_alias]\nhigh = "custom high"\n'
    )
    persona = resolve_persona(str(minimal))
    assert persona.id == "minimal"

    # Slot the minimal persona defines → its line wins.
    finding_hi = Finding(detector="missing_alias", severity=Severity.HIGH, message="x")
    assert persona.roast_for(finding_hi, fallback=default_persona()) == "custom high"

    # Slot only the default covers → fallback fills it in.
    finding_low = Finding(detector="slow_tool", severity=Severity.LOW, message="x")
    fallback_line = default_persona().roast_for(finding_low)
    assert persona.roast_for(finding_low, fallback=default_persona()) == fallback_line


def test_resolve_persona_unknown_id_raises() -> None:
    with pytest.raises(PersonaError):
        resolve_persona("does_not_exist_anywhere")


def test_persona_dir_lookup_finds_extra_file(tmp_path: Path) -> None:
    extra = tmp_path / "personas"
    extra.mkdir()
    (extra / "surfer.toml").write_text(
        'id = "surfer"\nname = "Surfer Bro"\n'
        '[roasts.missing_alias]\nhigh = "duuude alias it"\n'
    )
    persona = resolve_persona("surfer", extra_dir=extra)
    assert persona.id == "surfer"
    finding = Finding(detector="missing_alias", severity=Severity.HIGH, message="x")
    assert persona.roast_for(finding) == "duuude alias it"


def test_persona_from_config_reads_coach_section() -> None:
    cfg = {"coach": {"persona": "drill_sergeant"}}
    assert persona_from_config(cfg) == "drill_sergeant"

    # Fallback [personas].default is also honored.
    cfg2 = {"personas": {"default": "zen_master"}}
    assert persona_from_config(cfg2) == "zen_master"

    # No config, no persona.
    assert persona_from_config(None) is None
    assert persona_from_config({}) is None


def test_persona_dir_from_config() -> None:
    assert persona_dir_from_config(None) is None
    assert persona_dir_from_config({}) is None
    got = persona_dir_from_config({"coach": {"persona_dir": "/tmp/personas"}})
    assert got == Path("/tmp/personas")


def test_score_cli_persona_flag_swaps_roast_copy(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    rc = main(["score", "--days", "0", "--persona", "drill_sergeant"])
    assert rc == 0
    out = capsys.readouterr().out
    # Drill sergeant's takes header + copy should appear.
    assert "DROP AND GIVE ME" in out


def test_score_cli_unknown_persona_falls_back_gracefully(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    rc = main(["score", "--days", "0", "--persona", "does_not_exist"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "persona:" in out
    # Scorecard still rendered with default copy.
    assert "Coach's take:" in out


def test_score_json_includes_persona_metadata(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    rc = main(
        ["score", "--days", "0", "--json", "--persona", "zen_master", "--no-record"]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["persona"] == {"id": "zen_master", "name": "Zen Master"}


def test_score_config_default_persona(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setenv("HISTFILE", str(FIXTURES / "bash_history.txt"))
    cfg = tmp_path / "config.toml"
    cfg.write_text('[coach]\npersona = "passive_aggressive_pm"\n')
    rc = main(["score", "--days", "0", "--config", str(cfg)])
    assert rc == 0
    out = capsys.readouterr().out
    # Passive-aggressive PM's signature header.
    assert "circling back" in out.lower()


def test_personas_command_lists_builtins(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main(["personas"])
    assert rc == 0
    out = capsys.readouterr().out
    for pid in ("default", "drill_sergeant", "zen_master", "passive_aggressive_pm"):
        assert pid in out
