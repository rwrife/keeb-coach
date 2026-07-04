"""Render a ``Scorecard`` to the terminal with ``rich``.

Kept intentionally free of business logic: this module knows *how* to
show a scorecard, never *what* counts as a bad habit. Swap it for a
JSON/plain-text renderer without touching detectors or scoring.

M4 addition: one **roast line per weak area** (i.e. per detector that
produced findings). Roast text lives here — it's presentation, not
detection — and picks a line deterministically from the finding
severity so tests can pin the copy.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .detectors.base import Finding, Severity
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

# Per-detector roast copy — indexed by severity so a HIGH finding gets a
# rougher line than a LOW one. Deterministic on purpose: the report
# looks the same across runs unless the underlying findings changed.
_ROASTS: dict[str, dict[Severity, str]] = {
    "missing_alias": {
        Severity.LOW: "A little repetition never hurt anyone. But we could shorten this.",
        Severity.MEDIUM: "Your keyboard is starting to feel used. Alias it.",
        Severity.HIGH: "You have hands. Use them for something new. Alias it.",
    },
    "slow_tool": {
        Severity.LOW: "Living in 2015 is a choice.",
        Severity.MEDIUM: "The modern equivalents are one `brew install` away.",
        Severity.HIGH: "It is 2026. Please stop typing `grep`.",
    },
    "long_path": {
        Severity.LOW: "Your fingers have earned a shortcut. Try `cd -`.",
        Severity.MEDIUM: "That path is longer than my patience. `zoxide` it.",
        Severity.HIGH: "You're speedrunning tendinitis. Install `zoxide` today.",
    },
    "sudo_redo": {
        Severity.LOW: "Forgot sudo? It happens. `sudo !!` next time.",
        Severity.MEDIUM: "You have retyped an entire command as root. Please stop.",
        Severity.HIGH: "`sudo !!` — memorize it, tattoo it, live it.",
    },
}


def _worst_finding_by_detector(findings: tuple[Finding, ...]) -> dict[str, Finding]:
    """Group findings by detector id, keeping the highest-severity one.

    Ties break on insertion order (the sort in scoring already sorts by
    severity desc, so the first match per detector wins). This gives us
    "one roast per weak area" without hard-coding detector ids here.
    """
    worst: dict[str, Finding] = {}
    for f in findings:
        current = worst.get(f.detector)
        if current is None or f.severity > current.severity:
            worst[f.detector] = f
    return worst


def _roast_line(finding: Finding) -> str | None:
    """Pick the roast copy for this detector + severity."""
    detector_roasts = _ROASTS.get(finding.detector)
    if not detector_roasts:
        return None
    return detector_roasts.get(finding.severity)


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

    # Per-area roasts — one line per detector that fired. Rendered after
    # the table so the raw counts are still the first thing you see.
    worst = _worst_finding_by_detector(scorecard.findings)
    if not worst:
        return
    console.print()
    console.print("[bold magenta]Coach's take:[/bold magenta]")
    # Iterate in the same worst-first order the table used.
    seen: set[str] = set()
    for finding in scorecard.findings:
        if finding.detector in seen:
            continue
        seen.add(finding.detector)
        line = _roast_line(finding)
        if line is None:
            continue
        console.print(f"  [magenta]•[/magenta] [cyan]{finding.detector}[/cyan]: {line}")
