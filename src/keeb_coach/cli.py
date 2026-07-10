"""KeebCoach CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import load_config
from .detectors import ALL_DETECTORS
from .detectors.base import Finding
from .fixes import (
    ForbiddenTargetError,
    render_stdout,
    snippets_for,
    write_managed_block,
)
from .history.atuin import find_atuin, load_atuin
from .history.loader import find_history
from .history.parser import Command, parse_file
from .personas import (
    Persona,
    PersonaError,
    iter_persona_files,
    load_all_builtins,
    persona_dir_from_config,
    persona_from_config,
    resolve_persona,
)
from .report import render_scorecard, render_trend
from .scoring import Scorecard, score_findings
from .storage import (
    RunRecord,
    TrendDelta,
    default_db_path,
    format_delta_headline,
    recent_runs,
    record_run,
    trend_delta,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keeb-coach",
        description="Your terminal has a personal trainer now. 🏋️⌨️",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"keeb-coach {__version__}",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    score = sub.add_parser("score", help="Grade your recent shell history.")
    score.add_argument(
        "--days",
        type=int,
        default=30,
        help=(
            "Only grade commands from the last N days (default: 30). "
            "Commands without a timestamp are always included. Use 0 for no window."
        ),
    )
    score.add_argument(
        "--top",
        type=int,
        default=10,
        help="Show the top N most-run programs (default: 10).",
    )
    score.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a TOML config file (default: ~/.config/keeb-coach/config.toml).",
    )
    score.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit a machine-readable JSON scorecard to stdout instead of the "
            "rich TUI report. Great for scripting or piping into `jq`."
        ),
    )
    score.add_argument(
        "--db",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Override the SQLite streak DB path (default: "
            "$XDG_DATA_HOME/keeb-coach/history.db or "
            "~/.local/share/keeb-coach/history.db)."
        ),
    )
    score.add_argument(
        "--no-record",
        action="store_true",
        help=(
            "Don't persist this run to the streak DB. Use for one-off "
            "experiments or when you're grading somebody else's history."
        ),
    )
    score.add_argument(
        "--window",
        type=int,
        default=7,
        metavar="DAYS",
        help=(
            "Comparison window for the trend headline (default: 7). Coach "
            "compares the newest run to the most recent run older than "
            "this many days."
        ),
    )
    score.add_argument(
        "--atuin",
        dest="atuin",
        action="store_true",
        default=None,
        help=(
            "Read history from atuin's SQLite DB instead of the shell's "
            "plain history file. Unlocks exit-code aware detectors like "
            "failed_retype. Default: auto (uses atuin if its DB exists)."
        ),
    )
    score.add_argument(
        "--no-atuin",
        dest="atuin",
        action="store_false",
        help="Force the plain shell history source even if atuin is installed.",
    )
    score.add_argument(
        "--atuin-db",
        type=Path,
        default=None,
        metavar="PATH",
        help="Override the atuin DB path (default: ~/.local/share/atuin/history.db).",
    )
    score.add_argument(
        "--persona",
        type=str,
        default=None,
        metavar="NAME|PATH",
        help=(
            "Coach persona for the scorecard's roast lines. Accepts a "
            "built-in id (drill_sergeant, zen_master, "
            "passive_aggressive_pm, default), a path to a persona TOML "
            "file, or an id from `[coach] persona_dir`. Overrides the "
            "config default. Run `keeb-coach personas` to list."
        ),
    )

    personas_cmd = sub.add_parser(
        "personas",
        help="List available coach personas.",
        description=(
            "Print every built-in persona plus any TOML personas found "
            "in `[coach] persona_dir`."
        ),
    )
    personas_cmd.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a TOML config file (default: ~/.config/keeb-coach/config.toml).",
    )

    trend = sub.add_parser(
        "trend",
        help="Show your scorecard history over time.",
        description=(
            "Print the most recent recorded scorecards (from the SQLite "
            "streak DB) along with a small sparkline and a per-detector "
            "finding-count trend."
        ),
    )
    trend.add_argument(
        "--limit",
        type=int,
        default=14,
        help="How many recent runs to display (default: 14, max 100).",
    )
    trend.add_argument(
        "--db",
        type=Path,
        default=None,
        metavar="PATH",
        help="Override the SQLite streak DB path.",
    )
    trend.add_argument(
        "--window",
        type=int,
        default=7,
        metavar="DAYS",
        help=(
            "Comparison window for the trend headline (default: 7). Same "
            "semantics as `score --window`."
        ),
    )
    trend.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON trend to stdout.",
    )

    fixes = sub.add_parser(
        "fixes",
        help="Turn findings into copy-paste alias/function snippets.",
        description=(
            "Emit shell snippets (aliases/functions) for the current findings. "
            "Prints to stdout by default; pass --write PATH to update a managed "
            "block in a dedicated file (never .bashrc/.zshrc — we refuse those)."
        ),
    )
    fixes.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a TOML config file (default: ~/.config/keeb-coach/config.toml).",
    )
    fixes.add_argument(
        "--write",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Write snippets into PATH (default suggestion: ~/.keeb_aliases). "
            "Re-running is idempotent — the managed block is replaced in place, "
            "never appended."
        ),
    )
    fixes.add_argument(
        "--days",
        type=int,
        default=30,
        help=(
            "Only consider commands from the last N days (default: 30, matches "
            "`score`). Use 0 for no window."
        ),
    )
    fixes.add_argument(
        "--atuin",
        dest="atuin",
        action="store_true",
        default=None,
        help="Read history from atuin's SQLite DB (default: auto).",
    )
    fixes.add_argument(
        "--no-atuin",
        dest="atuin",
        action="store_false",
        help="Force the plain shell history source.",
    )
    fixes.add_argument(
        "--atuin-db",
        type=Path,
        default=None,
        metavar="PATH",
        help="Override the atuin DB path.",
    )
    return parser


def _filter_by_days(cmds: Sequence[Command], days: int) -> list[Command]:
    """Return only commands within the last ``days``.

    Commands without a timestamp are always kept — the alternative is to
    silently drop every zsh non-extended / bash-without-HISTTIMEFORMAT
    entry, which would make `--days` a footgun on the most common setup.
    ``days <= 0`` disables filtering entirely so scripts can opt out.
    """
    if days <= 0:
        return list(cmds)
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    return [c for c in cmds if c.ts is None or c.ts >= cutoff]


def _date_range(cmds: Sequence[Command]) -> tuple[datetime | None, datetime | None]:
    stamps = [c.ts for c in cmds if c.ts is not None]
    if not stamps:
        return None, None
    return min(stamps), max(stamps)


def _fmt_ts(ts: datetime | None) -> str:
    return ts.strftime("%Y-%m-%d %H:%M UTC") if ts else "unknown"


def _top_commands(cmds: Sequence[Command], n: int = 10) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for cmd in cmds:
        prog = cmd.program
        if prog:
            counter[prog] += 1
    return counter.most_common(n)


def _delta_to_json(delta: TrendDelta | None) -> dict[str, object] | None:
    """Serialize a :class:`TrendDelta` for JSON output.

    Kept separate from :func:`_scorecard_to_json` so both ``score`` and
    ``trend`` share one wire format for the delta block.
    """
    if delta is None:
        return None
    return {
        "window_days": delta.window_days,
        "score_delta": delta.score_delta,
        "findings_delta": dict(delta.findings_delta),
        "headline": format_delta_headline(delta),
        "reference": (
            {
                "id": delta.reference_run.id,
                "ts": delta.reference_run.ts.isoformat(),
                "score": delta.reference_run.score,
                "grade": delta.reference_run.grade,
            }
            if delta.reference_run
            else None
        ),
    }


def _run_to_json(run: RunRecord) -> dict[str, object]:
    return {
        "id": run.id,
        "ts": run.ts.isoformat(),
        "shell": run.shell,
        "history_path": run.history_path,
        "days": run.days,
        "total_commands": run.total_commands,
        "score": run.score,
        "grade": run.grade,
        "findings": dict(run.findings),
    }


def _resolve_active_persona(
    cli_value: str | None,
    config: dict[str, object] | None,
    console: Console,
) -> Persona:
    """Resolve the active persona from CLI + config, with a friendly fallback.

    CLI wins over config. A bad name prints a warning and falls back
    to the default persona so a typo never breaks the scorecard.
    """
    name = cli_value if cli_value else persona_from_config(config)
    extra_dir = persona_dir_from_config(config)
    try:
        return resolve_persona(name, extra_dir=extra_dir)
    except PersonaError as exc:
        console.print(f"[yellow]persona:[/yellow] {exc} [dim](falling back to default)[/dim]")
        return resolve_persona(None)


def _scorecard_to_json(
    scorecard: Scorecard,
    *,
    shell: str,
    history_path: Path,
    days: int,
    date_range: tuple[datetime | None, datetime | None],
    top: list[tuple[str, int]],
    delta: TrendDelta | None = None,
    persona: Persona | None = None,
) -> dict[str, object]:
    """Serialize a ``Scorecard`` into a stable JSON-friendly dict.

    The schema is intentionally flat and typed so scripts (`jq`, CI
    gates, dashboards) can consume it without knowing about ``rich`` or
    Python enums. Any future field additions should be additive so we
    don't break downstream tooling.
    """
    earliest, latest = date_range
    payload: dict[str, object] = {
        "schema": "keeb-coach.scorecard/v1",
        "version": __version__,
        "shell": shell,
        "history_path": str(history_path),
        "days": days,
        "total_commands": scorecard.total_commands,
        "date_range": {
            "earliest": earliest.isoformat() if earliest else None,
            "latest": latest.isoformat() if latest else None,
        },
        "score": scorecard.score,
        "grade": scorecard.grade,
        "findings": [
            {
                "detector": f.detector,
                "severity": f.severity.name.lower(),
                "severity_rank": int(f.severity),
                "message": f.message,
                "suggested_fix": f.suggested_fix,
                "evidence": f.evidence,
            }
            for f in scorecard.findings
        ],
        "top_commands": [
            {"command": prog, "count": count} for prog, count in top
        ],
    }
    delta_payload = _delta_to_json(delta)
    if delta_payload is not None:
        payload["trend"] = delta_payload
    if persona is not None:
        payload["persona"] = {"id": persona.id, "name": persona.name}
    return payload


@dataclass(frozen=True)
class _HistoryLoad:
    """Result of :func:`_load_history` — a resolved history source."""

    commands: list[Command]
    shell: str
    path: Path
    exists: bool


def _load_history(
    *,
    prefer_atuin: bool | None,
    atuin_db: Path | None,
) -> _HistoryLoad:
    """Pick a history source and return its parsed commands.

    ``prefer_atuin`` semantics:

    - ``True``   — user passed ``--atuin``; use atuin if the DB exists,
      otherwise fall back to plain shell (and note it in the header).
    - ``False``  — user passed ``--no-atuin``; always use plain shell.
    - ``None``   — auto: use atuin if its DB exists, otherwise plain shell.
    """
    atuin_src = find_atuin(atuin_db)
    use_atuin = prefer_atuin if prefer_atuin is not None else atuin_src.exists
    if use_atuin and atuin_src.exists:
        return _HistoryLoad(
            commands=load_atuin(atuin_db),
            shell="atuin",
            path=atuin_src.path,
            exists=True,
        )
    plain = find_history()
    return _HistoryLoad(
        commands=parse_file(plain.shell, plain.path) if plain.exists else [],
        shell=plain.shell,
        path=plain.path,
        exists=plain.exists,
    )


def _run_detectors(
    commands: Sequence[Command],
    config: dict[str, object] | None = None,
) -> list[Finding]:
    """Run every registered detector and flatten their findings.

    Each detector receives the ``detectors`` sub-dict directly so it can
    pluck its own ``[detectors.<id>]`` section from the merged config.
    """
    detector_cfg: dict[str, object] | None = None
    if config is not None:
        raw = config.get("detectors")
        if isinstance(raw, dict):
            detector_cfg = raw
    findings: list[Finding] = []
    for detector in ALL_DETECTORS:
        findings.extend(detector.run(commands, detector_cfg))
    return findings


def cmd_score(args: argparse.Namespace, console: Console) -> int:
    """Parse history, run detectors, print scorecard (or JSON)."""
    _hist = _load_history(
        prefer_atuin=getattr(args, "atuin", None),
        atuin_db=getattr(args, "atuin_db", None),
    )

    class _Src:  # tiny shim so downstream reads stay readable.
        shell = _hist.shell
        path = _hist.path
        exists = _hist.exists

    src = _Src()

    if not src.exists:
        if args.json:
            # A missing history file is still a valid, empty scorecard —
            # emit valid JSON so scripts don't have to special-case it.
            payload = {
                "schema": "keeb-coach.scorecard/v1",
                "version": __version__,
                "shell": src.shell,
                "history_path": str(src.path),
                "days": args.days,
                "total_commands": 0,
                "date_range": {"earliest": None, "latest": None},
                "score": 100,
                "grade": "A",
                "findings": [],
                "top_commands": [],
                "note": "history file not found",
            }
            print(json.dumps(payload, indent=2))
            return 0
        header_lines = [
            "[bold]Coach is warming up 🏋️[/bold]",
            "",
            f"Detected shell: [cyan]{src.shell}[/cyan]",
            f"History file:   [cyan]{src.path}[/cyan]",
            "Exists:         [yellow]no[/yellow]",
            "",
            "[dim]No history file yet — nothing to grade. "
            "Run some commands first, coach.[/dim]",
        ]
        console.print(
            Panel.fit("\n".join(header_lines), title="keeb-coach", border_style="magenta")
        )
        return 0

    config = load_config(args.config)
    persona = _resolve_active_persona(getattr(args, "persona", None), config, console)
    all_commands = _hist.commands
    commands = _filter_by_days(all_commands, args.days)
    earliest, latest = _date_range(commands)
    findings = _run_detectors(commands, config)
    scorecard = score_findings(findings, total_commands=len(commands))
    top = _top_commands(commands, n=args.top)

    # Record the run *before* computing the delta so today's row is in
    # the DB (but ``trend_delta`` deliberately compares against an
    # *older* reference run, so it still shows week-over-week movement).
    record_error: str | None = None
    if not args.no_record:
        try:
            record_run(
                scorecard,
                shell=src.shell,
                history_path=src.path,
                days=args.days,
                db_path=args.db,
            )
        except (OSError, sqlite3.DatabaseError) as exc:  # pragma: no cover
            # Never fail the scorecard because the streak DB was cranky.
            record_error = str(exc)

    delta: TrendDelta | None = None
    try:
        delta = trend_delta(window_days=args.window, db_path=args.db)
    except sqlite3.DatabaseError:  # pragma: no cover
        delta = None

    if args.json:
        payload = _scorecard_to_json(
            scorecard,
            shell=src.shell,
            history_path=src.path,
            days=args.days,
            date_range=(earliest, latest),
            top=top,
            delta=delta,
            persona=persona,
        )
        if record_error is not None:  # pragma: no cover
            payload["record_error"] = record_error
        print(json.dumps(payload, indent=2))
        return 0

    header_lines = [
        "[bold]Coach is warming up 🏋️[/bold]",
        "",
        f"Detected shell: [cyan]{src.shell}[/cyan]",
        f"History file:   [cyan]{src.path}[/cyan]",
        "Exists:         [green]yes[/green]",
        "",
        f"Total commands: [bold]{len(commands)}[/bold]"
        + (
            f" [dim](of {len(all_commands)} total, last {args.days}d)[/dim]"
            if args.days > 0 and len(commands) != len(all_commands)
            else ""
        ),
        f"Date range:     {_fmt_ts(earliest)}  →  {_fmt_ts(latest)}",
    ]
    console.print(Panel.fit("\n".join(header_lines), title="keeb-coach", border_style="magenta"))

    render_scorecard(scorecard, console, persona=persona)

    headline = format_delta_headline(delta)
    if headline:
        console.print()
        console.print(f"[bold magenta]Trend:[/bold magenta] {headline}")

    if top:
        table = Table(title=f"Top {len(top)} commands", header_style="bold magenta")
        table.add_column("#", justify="right", style="dim", no_wrap=True)
        table.add_column("command", style="cyan", no_wrap=True)
        table.add_column("count", justify="right", style="green")
        for i, (prog, count) in enumerate(top, start=1):
            table.add_row(str(i), prog, str(count))
        console.print(table)

    console.print("[dim]v0.1: full detector set + roasts + config + fixes online.[/dim]")
    return 0


def cmd_trend(args: argparse.Namespace, console: Console) -> int:
    """Show the recent-runs table + sparkline + delta headline.

    Reads from the same SQLite DB that ``score`` writes to. If there's
    no DB yet, prints a gentle nudge instead of crashing — first-run
    UX matters.
    """
    limit = max(1, min(int(args.limit), 100))
    db = args.db if args.db is not None else default_db_path()
    runs = recent_runs(limit=limit, db_path=args.db)
    delta = trend_delta(window_days=args.window, db_path=args.db)

    if args.json:
        payload: dict[str, object] = {
            "schema": "keeb-coach.trend/v1",
            "version": __version__,
            "db_path": str(db),
            "window_days": args.window,
            "runs": [_run_to_json(r) for r in runs],
            "trend": _delta_to_json(delta),
        }
        print(json.dumps(payload, indent=2))
        return 0

    if not runs:
        console.print(
            "[yellow]No streak history yet.[/yellow] "
            "[dim]Run `keeb-coach score` a couple of times to build one.[/dim]"
        )
        console.print(f"[dim]DB path: {db}[/dim]")
        return 0

    render_trend(runs, delta, console, db_path=db)
    return 0


def cmd_fixes(args: argparse.Namespace, console: Console) -> int:
    """M5: emit alias snippets for the current findings.

    Same detection pipeline as ``score`` — we don't invent findings
    here, we just render them. That means ``fixes`` and ``score``
    always agree about what needs fixing.
    """
    _hist = _load_history(
        prefer_atuin=getattr(args, "atuin", None),
        atuin_db=getattr(args, "atuin_db", None),
    )

    class _Src:
        shell = _hist.shell
        path = _hist.path
        exists = _hist.exists

    src = _Src()
    if not src.exists:
        console.print(
            "[yellow]No history file yet — nothing to fix.[/yellow] "
            f"[dim](looked for: {src.path})[/dim]"
        )
        return 0

    config = load_config(args.config)
    all_commands = _hist.commands
    commands = _filter_by_days(all_commands, args.days)
    findings = _run_detectors(commands, config)
    scorecard = score_findings(findings, total_commands=len(commands))
    # Use the scored (severity-sorted) findings so the snippet order
    # matches what the scorecard shows — worst first.
    snippets = snippets_for(scorecard.findings)

    if args.write is None:
        # ``rich``'s console would re-wrap and colorize shell text; use
        # a plain print so the output is copy-paste-ready.
        print(render_stdout(snippets), end="")
        return 0

    try:
        target = write_managed_block(args.write, snippets)
    except ForbiddenTargetError as exc:
        console.print(f"[red]error:[/red] {exc}")
        return 2
    except OSError as exc:
        console.print(f"[red]error:[/red] could not write {args.write}: {exc}")
        return 1

    console.print(
        f"[green]wrote[/green] {len(snippets)} snippet(s) to [cyan]{target}[/cyan]"
    )
    console.print(
        f"[dim]source it in your shell: `source {target}`[/dim]"
    )
    return 0


def cmd_personas(args: argparse.Namespace, console: Console) -> int:
    """List every persona the CLI can resolve."""
    config = load_config(args.config)
    configured = persona_from_config(config)
    extra_dir = persona_dir_from_config(config)

    table = Table(title="coach personas", header_style="bold magenta")
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("name")
    table.add_column("source", style="dim", no_wrap=True)
    table.add_column("description")

    default_marker = configured or "default"
    for persona in load_all_builtins():
        pid = persona.id
        marker = " (default)" if pid == default_marker else ""
        table.add_row(pid + marker, persona.name, "builtin", persona.description)

    if extra_dir is not None:
        for pid, path in iter_persona_files(extra_dir):
            try:
                persona = resolve_persona(pid, extra_dir=extra_dir)
            except PersonaError as exc:
                table.add_row(pid, "[red]invalid[/red]", str(path), str(exc))
                continue
            marker = " (default)" if pid == default_marker else ""
            table.add_row(persona.id + marker, persona.name, str(path), persona.description)

    console.print(table)
    if configured:
        console.print(f"[dim]configured default: {configured}[/dim]")
    else:
        console.print(
            "[dim]tip: set `[coach] persona = \"drill_sergeant\"` in "
            "~/.config/keeb-coach/config.toml to change the default.[/dim]"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    console = Console()

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "score":
        return cmd_score(args, console)
    if args.command == "fixes":
        return cmd_fixes(args, console)
    if args.command == "trend":
        return cmd_trend(args, console)
    if args.command == "personas":
        return cmd_personas(args, console)

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
