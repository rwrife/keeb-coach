# KeebCoach 🏋️⌨️

> Your terminal has a personal trainer now. It saw that `cd ../../../projects/foo` you typed for the 40th time. It is not impressed.

## 1. Pitch

**KeebCoach** replays your real shell history and grades *how efficiently you type* — not what you did, but how ergonomically you did it. It spots the long paths you retype instead of `cd -`, the 30-char commands you ran 40 times without an alias, the `grep`/`find`/`cat` you keep reaching for when `rg`/`fd`/`bat` are sitting right there, and the arrow-key marathons through your history. Then it hands you a daily **efficiency scorecard** with a letter grade, your worst habits, and copy-paste fixes.

Think of it as screen-time-for-your-keyboard-ergonomics: a fitness tracker for the way you drive a terminal.

## 2. Trend inspiration

Scanned trends on 2026-07-01. What pointed here:

- **The "reduce terminal friction" wave.** [7 Modern CLI Tools You Must Try in 2026 (Medium)](https://medium.com/the-software-journal/7-modern-cli-tools-you-must-try-in-2026-c4ecab6a9928) is entirely about tools that shave keystrokes — **Zoxide** (fuzzy `cd` that learns), **Starship** (context-aware prompt), **Nushell** (structured data instead of string-mangling). The whole 2026 CLI zeitgeist is "type less, think more." Nobody measures whether *you personally* are actually doing that.
- **Screen-time / coaching utilities are hot.** [Neowin's Top 10 Windows 11 apps for 2026](https://www.neowin.net/news/top-10-cool-and-useful-apps-for-windows-11-in-2026/) highlights screen-time utilities, activity-history trackers (AppControl logs app launches + resource load over 3 days), and "just plain fun" tools. KeebCoach applies that self-quantification lens to the terminal.
- **Terminal Renaissance.** [Modern TUI Tools Reshaping Developer Workflows (1337skills)](https://1337skills.com/blog/2026-03-09-terminal-renaissance-modern-tui-tools-reshaping-developer-workflows/) shows TUIs (Posting, Yazi, Harlequin) are exploding. A scorecard TUI fits the moment.
- **`awesome-tuis` / Terminal Trove** momentum — a steady appetite for small, opinionated terminal toys with personality.

The synthesis: everyone ships tools to *make* you faster (zoxide, aliases, rg). Nobody ships a tool that *audits whether you're leaving that speed on the table* and nags you, with jokes, into fixing it.

## 3. Why it's different

- **vs. `thefuck` / `pay-respects`:** those correct a *single* failed command in the moment. KeebCoach never corrects live — it does *longitudinal analysis* of your habits and generates a *permanent* personalized alias/config file. Different job entirely.
- **vs. `zoxide` / `mcfly` / `atuin`:** those *are* the efficiency tools you install. KeebCoach *grades whether you're actually using tools like them*, and recommends them by name when it sees you doing it the slow way. It's the coach, not the equipment.
- **vs. `yak-tracker` (existing rwrife repo):** yak-tracker reconstructs *what you did* as a yak-shaving narrative/standup. KeebCoach measures *HOW efficiently you did it* — pure ergonomics scoring, no story. Zero overlap in output.
- **vs. `quackpack` / `quipkit` (existing rwrife repos):** those *store* snippets/queries/replies for reuse. KeebCoach *detects that you should have stored something* and drafts the alias for you.
- **Personality is the moat.** The scorecard roasts you. "You typed `git status` 87 times. You have hands. Use `gs`. — Coach"

## 4. MVP scope (v0.1)

The smallest useful thing:

- `keeb-coach score` — parse the user's shell history file (bash/zsh), analyze the last N days, print a scorecard to the terminal.
- **Detectors (v0.1 ships 4):**
  1. **Missing-alias** — any command run ≥ threshold times with length ≥ N chars → "alias this."
  2. **Long-path retype** — repeated absolute/deep-relative `cd` targets → suggest `cd -`, `zoxide`, or a shell var.
  3. **Slow-tool** — `grep`→`rg`, `find`→`fd`, `cat`→`bat`, `ls -la`→`eza`, `curl | jq`→`xh` (config-driven map).
  4. **Sudo-redo** — `command` immediately followed by `sudo !!` pattern (you forgot sudo, then retyped).
- **Letter grade** (A–F) from a weighted score, plus a one-line roast per weak area.
- `keeb-coach fixes` — emit a copy-paste block of suggested aliases/functions (and a `--write ~/.keeb_aliases` option, opt-in only).
- 100% local. Reads only history files. No network, no telemetry, no daemon.
- Config file `~/.config/keeb-coach/config.toml` for thresholds + the slow-tool map.

## 5. Tech stack

Boring, fast, and cross-platform:

- **Python 3.11+** — history parsing is string-wrangling and dict-counting; Python is fastest to build and trivially cross-platform. Zero compile step for M1.
- **stdlib-first** — `argparse`, `collections.Counter`, `pathlib`, `tomllib` (3.11 stdlib) for config. No heavy deps for the core.
- **`rich`** — for the scorecard rendering (tables, color, the letter-grade banner). One dependency, huge payoff, widely trusted.
- **`pytest`** — golden-file tests against fixture history files.
- Packaged via `pyproject.toml` (PEP 621) → `pipx install keeb-coach`.

Why not Rust/Go: v1 is I/O + counting, not perf-bound. Python gets a working, extensible tool shipped in a day; a hot-loop rewrite can come later if a detector ever needs it.

## 6. Architecture

```
keeb_coach/
  cli.py           # argparse entrypoint: score | fixes | detectors
  history/
    loader.py      # locate + read history (bash HISTFILE, zsh extended, fish)
    parser.py      # normalize lines -> Command(ts, raw, argv, cwd?)
  detectors/
    base.py        # Detector protocol: run(commands, cfg) -> list[Finding]
    missing_alias.py
    long_path.py
    slow_tool.py
    sudo_redo.py
  scoring.py       # Finding[] -> weighted score -> letter grade
  report.py        # rich scorecard + roast lines
  fixes.py         # Finding[] -> alias/function snippets
  config.py        # load/merge TOML config + defaults
tests/
  fixtures/*.history
```

Key idea: **detectors are pluggable.** Each implements one interface and returns `Finding` objects (severity, message, suggested_fix). Adding a new habit to catch = one file + a registry entry. Scoring and reporting never change.

## 7. Milestones (each shippable)

1. **M1 — Scaffold + hello-world.** `pyproject.toml`, package skeleton, `keeb-coach --version`, `keeb-coach score` prints "Coach is warming up 🏋️" and the detected history file path. CI (ruff + pytest) green.
2. **M2 — History ingestion.** `loader` + `parser` for bash and zsh (incl. zsh extended `: <ts>:0;cmd`). `keeb-coach score` prints total commands, date range, top 10 commands. Fixture-based tests.
3. **M3 — First two detectors + scoring skeleton.** `missing_alias` + `slow_tool`, `Finding` model, naive weighted score + letter grade. Scorecard renders via `rich`.
4. **M4 — Remaining v0.1 detectors + roasts.** `long_path` + `sudo_redo`. Per-area roast lines. Config-driven thresholds and slow-tool map with sane defaults.
5. **M5 — `fixes` command.** Generate alias/function snippets from findings; `--write` to an opt-in file with a clearly-marked managed block. Idempotent (never dupes on re-run).
6. **M6 — Polish + release v0.1.** `--days N`, `--json` output, README with GIF/asciinema, `pipx` install docs, tagged `v0.1.0` release.

## 8. Backlog / future features (v0.2+)

1. **`keeb-coach watch`** — optional lightweight daemon/precmd hook that emits a tiny nudge only when a *new* bad habit crosses threshold (not every command — no `thefuck` spam).
2. **Streaks & progress** — track score over time in a local SQLite; "you cut retyped paths 60% this week 💪."
3. **Fish + PowerShell + Nushell history** parsers.
4. **Atuin integration** — read atuin's richer history DB (exit codes, cwd, duration) for exit-code-aware detectors.
5. **Exit-code detectors** — with cwd/duration data: flag commands that fail then get retyped, slow commands that have faster equivalents.
6. **Coach personas** — swappable roast voices (Drill Sergeant, Zen Master, Passive-Aggressive PM), mirroring the fun-persona trend.
7. **Team leaderboard (opt-in, local export)** — export an anonymized scorecard to share; "office keyboard-ergonomics standings."
8. **Shell-native alias detection** — actually parse the user's existing aliases/functions so KeebCoach never suggests one they already have.
9. **`keeb-coach explain <cmd>`** — paste any command, get the leaner equivalent + why.
10. **Typo graveyard** — surface commands that failed purely on typos and suggest correction aliases.
11. **VS Code / Warp / Ghostty terminal integration** — surface the scorecard in-editor.
12. **Achievements** — "Aliased 10 commands," "Went a full day without a single `cd ../../..`."

## 9. Out of scope

- **Live in-the-moment correction.** That's `thefuck`/`pay-respects` territory; we deliberately don't compete.
- **Keylogging or capturing anything beyond the shell history file.** No global keyboard hooks, ever.
- **Any network calls, cloud sync, or telemetry** in the core. Local-first is a hard rule.
- **Being your shell / prompt / history backend.** We *read* history; we don't replace zoxide/atuin/starship.
- **Auto-editing your `.bashrc`/`.zshrc`.** We only ever write to a separate opt-in file that you choose to source.
- **Multi-user server dashboards.** This is a personal, single-user tool.
