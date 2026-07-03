"""Render a ``Scorecard`` to the terminal with ``rich``.

Kept intentionally free of business logic: this module knows *how* to
show a scorecard, never *what* counts as a bad habit. Swap it for a
JSON/plain-text renderer without touching detectors or scoring.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .detectors.base import Severity
from .scoring import Scorecard

# Color per grade for the big banner. Muted enough to survive on both
# light and dark terminals.
_GRADE_STYLE: dict[str, str] = {
    "A": "bold bright_green",
    "B": "bold green",
    "C": "bold yellow",
    "D": "bold orange1",
    "F": "bold red",
}

_SEVERITY_STYLE: dict[Severity, str] = {
    Severity.LOW: "yellow",
    Severity.MEDIUM: "orange1",
    Severity.HIGH: "red",
}

_SEVERITY_LABEL: dict[Severity, str] = {
    Severity.LOW: "low",
    Severity.MEDIUM: "med",
    Severity.HIGH: "high",
}


def render_scorecard(scorecard: Scorecard, console: Console) -> None:
    """Print the scorecard banner + a findings table (or a clean-slate note)."""
    style = _GRADE_STYLE.get(scorecard.grade, "bold white")
    banner = Text.assemble(
        (f"{scorecard.grade}", style),
        (f"   {scorecard.score}/100", "bold white"),
        (f"   ({scorecard.total_commands} commands analyzed)", "dim"),
    )
    console.print(Panel.fit(banner, title="Efficiency scorecard", border_style="magenta"))

    if not scorecard.has_findings:
        console.print(
            "[green]Clean sheet — no habits worth fixing.[/green] "
            "[dim]Coach is suspicious but proud.[/dim]"
        )
        return

    table = Table(header_style="bold magenta", expand=False)
    table.add_column("severity", no_wrap=True)
    table.add_column("detector", no_wrap=True, style="cyan")
    table.add_column("finding")
    for finding in scorecard.findings:
        sev_style = _SEVERITY_STYLE.get(finding.severity, "white")
        table.add_row(
            Text(_SEVERITY_LABEL[finding.severity], style=sev_style),
            finding.detector,
            finding.message,
        )
    console.print(table)
