"""KeebCoach CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
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
from .history.loader import find_history
from .history.parser import Command, parse_file
from .report import render_scorecard
from .scoring import Scorecard, score_findings


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


def _scorecard_to_json(
    scorecard: Scorecard,
    *,
    shell: str,
    history_path: Path,
    days: int,
    date_range: tuple[datetime | None, datetime | None],
    top: list[tuple[str, int]],
) -> dict[str, object]:
    """Serialize a ``Scorecard`` into a stable JSON-friendly dict.

    The schema is intentionally flat and typed so scripts (`jq`, CI
    gates, dashboards) can consume it without knowing about ``rich`` or
    Python enums. Any future field additions should be additive so we
    don't break downstream tooling.
    """
    earliest, latest = date_range
    return {
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
    src = find_history()

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
    all_commands = parse_file(src.shell, src.path)
    commands = _filter_by_days(all_commands, args.days)
    earliest, latest = _date_range(commands)
    findings = _run_detectors(commands, config)
    scorecard = score_findings(findings, total_commands=len(commands))
    top = _top_commands(commands, n=args.top)

    if args.json:
        payload = _scorecard_to_json(
            scorecard,
            shell=src.shell,
            history_path=src.path,
            days=args.days,
            date_range=(earliest, latest),
            top=top,
        )
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

    render_scorecard(scorecard, console)

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


def cmd_fixes(args: argparse.Namespace, console: Console) -> int:
    """M5: emit alias snippets for the current findings.

    Same detection pipeline as ``score`` — we don't invent findings
    here, we just render them. That means ``fixes`` and ``score``
    always agree about what needs fixing.
    """
    src = find_history()
    if not src.exists:
        console.print(
            "[yellow]No history file yet — nothing to fix.[/yellow] "
            f"[dim](looked for: {src.path})[/dim]"
        )
        return 0

    config = load_config(args.config)
    all_commands = parse_file(src.shell, src.path)
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

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
