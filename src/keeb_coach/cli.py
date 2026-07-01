"""KeebCoach CLI entrypoint."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from rich.console import Console
from rich.panel import Panel

from . import __version__
from .history.loader import find_history


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


def cmd_score(args: argparse.Namespace, console: Console) -> int:
    """M1 hello-world: report the detected history file and warm up."""
    src = find_history()
    body_lines = [
        "[bold]Coach is warming up 🏋️[/bold]",
        "",
        f"Detected shell: [cyan]{src.shell}[/cyan]",
        f"History file:   [cyan]{src.path}[/cyan]",
        f"Exists:         {'[green]yes[/green]' if src.exists else '[yellow]no[/yellow]'}",
    ]
    if not src.exists:
        body_lines.append("")
        body_lines.append(
            "[dim]No history file yet — nothing to grade. "
            "Run some commands first, coach.[/dim]"
        )
    else:
        body_lines.append("")
        body_lines.append("[dim]M1 scaffold only — real scoring lands in M3.[/dim]")

    console.print(Panel.fit("\n".join(body_lines), title="keeb-coach", border_style="magenta"))
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
