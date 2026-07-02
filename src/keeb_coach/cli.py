"""KeebCoach CLI entrypoint."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .history.loader import find_history
from .history.parser import Command, parse_file


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
        help="How many days of history to grade (default: 30). [reserved for M2+]",
    )
    return parser


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


def cmd_score(args: argparse.Namespace, console: Console) -> int:
    """M2: parse history and print totals, date range, and top-10 commands."""
    src = find_history()
    header_lines = [
        "[bold]Coach is warming up 🏋️[/bold]",
        "",
        f"Detected shell: [cyan]{src.shell}[/cyan]",
        f"History file:   [cyan]{src.path}[/cyan]",
        f"Exists:         {'[green]yes[/green]' if src.exists else '[yellow]no[/yellow]'}",
    ]

    if not src.exists:
        header_lines.append("")
        header_lines.append(
            "[dim]No history file yet — nothing to grade. "
            "Run some commands first, coach.[/dim]"
        )
        console.print(
            Panel.fit("\n".join(header_lines), title="keeb-coach", border_style="magenta")
        )
        return 0

    commands = parse_file(src.shell, src.path)
    earliest, latest = _date_range(commands)
    header_lines.extend(
        [
            "",
            f"Total commands: [bold]{len(commands)}[/bold]",
            f"Date range:     {_fmt_ts(earliest)}  →  {_fmt_ts(latest)}",
        ]
    )
    console.print(Panel.fit("\n".join(header_lines), title="keeb-coach", border_style="magenta"))

    top = _top_commands(commands, n=10)
    if top:
        table = Table(title="Top 10 commands", header_style="bold magenta")
        table.add_column("#", justify="right", style="dim", no_wrap=True)
        table.add_column("command", style="cyan", no_wrap=True)
        table.add_column("count", justify="right", style="green")
        for i, (prog, count) in enumerate(top, start=1):
            table.add_row(str(i), prog, str(count))
        console.print(table)
    else:
        console.print("[dim]No parsable commands found.[/dim]")

    console.print("[dim]M2 ingestion only — real scoring lands in M3.[/dim]")
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

    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
