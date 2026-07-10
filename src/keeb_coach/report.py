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

from collections.abc import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .detectors.base import Finding, Severity
from .personas import Persona, default_persona
from .scoring import Scorecard
from .storage import (
    RunRecord,
    TrendDelta,
    format_delta_headline,
    score_series,
    sparkline,
)

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


def _roast_line(finding: Finding, persona: Persona, fallback: Persona) -> str | None:
    """Pick the roast copy for this detector + severity from ``persona``.

    Falls back to ``fallback`` (the default persona) for any slot the
    active persona doesn't override — so a persona only has to write
    the lines it wants to change.
    """
    return persona.roast_for(finding, fallback=fallback)


def render_scorecard(
    scorecard: Scorecard,
    console: Console,
    *,
    persona: Persona | None = None,
) -> None:
    """Print the scorecard banner + a findings table (or a clean-slate note).

    ``persona`` selects the roast voice. When ``None``, the default
    persona is used and output matches the pre-personas M4 behavior.
    """
    fallback = default_persona()
    active = persona if persona is not None else fallback
    style = _GRADE_STYLE.get(scorecard.grade, "bold white")
    banner = Text.assemble(
        (f"{scorecard.grade}", style),
        (f"   {scorecard.score}/100", "bold white"),
        (f"   ({scorecard.total_commands} commands analyzed)", "dim"),
    )
    console.print(Panel.fit(banner, title="Efficiency scorecard", border_style="magenta"))

    if not scorecard.has_findings:
        clean = active.string(
            "clean_sheet",
            fallback=fallback,
            default="Clean sheet — no habits worth fixing. Coach is suspicious but proud.",
        )
        console.print(f"[green]{clean}[/green]")
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
    header = active.string(
        "takes_header", fallback=fallback, default="Coach's take:"
    )
    console.print()
    console.print(f"[bold magenta]{header}[/bold magenta]")
    # Iterate in the same worst-first order the table used.
    seen: set[str] = set()
    for finding in scorecard.findings:
        if finding.detector in seen:
            continue
        seen.add(finding.detector)
        line = _roast_line(finding, active, fallback)
        if line is None:
            continue
        console.print(f"  [magenta]•[/magenta] [cyan]{finding.detector}[/cyan]: {line}")


_TREND_GRADE_STYLE: dict[str, str] = {
    "A": "bright_green",
    "B": "green",
    "C": "yellow",
    "D": "orange1",
    "F": "red",
}


def _fmt_delta(delta: int) -> str:
    """Render an integer delta with a sign for the trend table.

    Positive deltas get a leading ``+``; zero stays bare so the eye
    doesn't get pulled to the noise.
    """
    if delta > 0:
        return f"+{delta}"
    if delta < 0:
        return str(delta)
    return "0"


def _detector_columns(runs: Sequence[RunRecord]) -> list[str]:
    """Stable list of detector ids across ``runs`` for the trend table.

    Sorted alphabetically so the column order is deterministic across
    invocations and snapshot-friendly for tests.
    """
    seen: set[str] = set()
    for run in runs:
        seen.update(run.findings)
    return sorted(seen)


def render_trend(
    runs: Sequence[RunRecord],
    delta: TrendDelta | None,
    console: Console,
    *,
    db_path: object | None = None,
) -> None:
    """Print the ``trend`` command's rich output.

    ``runs`` is expected newest-first (that's what ``recent_runs``
    returns); the sparkline internally re-sorts oldest-first so the
    left-to-right visual matches wall-clock time.
    """
    if not runs:
        # Callers already special-case empty DBs; this branch keeps
        # the function safe to import and reuse.
        console.print("[dim]No trend data yet.[/dim]")
        return

    latest = runs[0]
    scores = score_series(runs)
    spark = sparkline(scores)
    lo, hi = min(scores), max(scores)
    headline = format_delta_headline(delta)

    banner_lines = [
        f"[bold]{len(runs)}[/bold] recorded run(s)",
        (
            "Latest: [bold]{grade}[/bold] {score}/100 "
            "[dim]({ts})[/dim]"
        ).format(
            grade=latest.grade,
            score=latest.score,
            ts=latest.ts.strftime("%Y-%m-%d %H:%M UTC"),
        ),
        f"Scores:  [magenta]{spark}[/magenta] [dim](min {lo}, max {hi})[/dim]",
    ]
    if headline:
        banner_lines.append(f"[magenta]{headline}[/magenta]")
    if db_path is not None:
        banner_lines.append(f"[dim]db: {db_path}[/dim]")

    console.print(
        Panel.fit(
            "\n".join(banner_lines),
            title="keeb-coach trend",
            border_style="magenta",
        )
    )

    detectors = _detector_columns(runs)
    table = Table(header_style="bold magenta", expand=False)
    table.add_column("when", no_wrap=True, style="dim")
    table.add_column("grade", justify="center", no_wrap=True)
    table.add_column("score", justify="right", no_wrap=True)
    table.add_column("cmds", justify="right", no_wrap=True, style="dim")
    for det in detectors:
        table.add_column(det, justify="right", no_wrap=True)

    # Iterate oldest-first in the table so it reads top-down like a log.
    for run in sorted(runs, key=lambda r: r.ts):
        grade_style = _TREND_GRADE_STYLE.get(run.grade, "white")
        row: list[object] = [
            run.ts.strftime("%Y-%m-%d %H:%M"),
            Text(run.grade, style=f"bold {grade_style}"),
            str(run.score),
            str(run.total_commands),
        ]
        for det in detectors:
            row.append(str(run.findings.get(det, 0)))
        table.add_row(*row)
    console.print(table)

    if delta is None or delta.reference_run is None:
        # Single-run DB or no eligible reference — nothing more to say.
        return

    # Delta panel: score movement + per-detector diff vs. the reference.
    diff_lines = [
        (
            "Compared to run "
            f"[cyan]#{delta.reference_run.id}[/cyan] "
            f"[dim]({delta.reference_run.ts.strftime('%Y-%m-%d %H:%M UTC')})[/dim]"
        ),
        (
            "Score: "
            f"[bold]{_fmt_delta(delta.score_delta)}[/bold] "
            f"({delta.reference_run.score} → {delta.latest.score})"
        ),
    ]
    if delta.findings_delta:
        for det, diff in sorted(delta.findings_delta.items()):
            style = "green" if diff < 0 else ("red" if diff > 0 else "dim")
            diff_lines.append(
                f"  [cyan]{det}[/cyan]: [{style}]{_fmt_delta(diff)}[/{style}] "
                f"({delta.reference_run.findings.get(det, 0)} → "
                f"{delta.latest.findings.get(det, 0)})"
            )
    console.print(
        Panel.fit(
            "\n".join(diff_lines),
            title=f"vs. {delta.window_days}d ago",
            border_style="magenta",
        )
    )
