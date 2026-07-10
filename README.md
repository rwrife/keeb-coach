# KeebCoach 🏋️⌨️

**Your terminal has a personal trainer now.** KeebCoach replays your real shell history and grades *how efficiently you type* — then hands you a daily scorecard with a letter grade, your worst habits, and copy-paste fixes.

It's not `thefuck`. It never corrects you live. It watches your patterns over time and coaches you into faster habits — with jokes.

> You typed `git status` 87 times. You have hands. Use `gs`. — Coach

## What it catches (v0.1)

- **Missing aliases** — long commands you run over and over.
- **Long-path retypes** — deep `cd` targets you keep typing instead of `cd -` / `zoxide`.
- **Slow tools** — `grep`→`rg`, `find`→`fd`, `cat`→`bat`, `ls -la`→`eza`.
- **Sudo-redos** — the "forgot sudo, retyped the whole thing" classic.
- **Failed retypes** *(atuin only)* — commands that fail and get retyped nearly verbatim (typos, missing sudo, wrong path). Needs exit-code data, which plain bash/zsh history doesn't record.

## Optional: atuin integration

If you use [atuin](https://atuin.sh) (a shell-history replacement that records exit code, cwd, and duration per command), KeebCoach reads its SQLite DB automatically and unlocks the exit-code-aware detectors above.

```bash
keeb-coach score              # auto: uses atuin if ~/.local/share/atuin/history.db exists
keeb-coach score --atuin      # force atuin (falls back to plain history if DB missing)
keeb-coach score --no-atuin   # force plain shell history
keeb-coach score --atuin-db /custom/path/history.db
```

Read-only, local-first, zero extra dependencies — same rules as the rest of the tool.

## What it tracks over time

- **Streak DB** — every `score` run appends to a local SQLite database.
- **`keeb-coach trend`** — sparkline + per-detector trend + week-over-week delta.
- **One-line headlines** on `score` ("You cut retyped paths 60% this week 💪").

## Quick start

### Install with `pipx` (recommended)

[`pipx`](https://pipx.pypa.io/) installs KeebCoach into an isolated venv and puts
`keeb-coach` on your `PATH` — the ergonomic default for a personal CLI.

```bash
# One-time setup, if you don't already have pipx:
python3 -m pip install --user pipx
python3 -m pipx ensurepath   # then restart your shell

# Install (from PyPI, once published):
pipx install keeb-coach

# ...or straight from GitHub in the meantime:
pipx install "git+https://github.com/rwrife/keeb-coach@v0.1.0"

# Upgrade later:
pipx upgrade keeb-coach
```

Prefer plain `pip`? `pip install --user keeb-coach` works too.

### First run

```bash
keeb-coach score          # grade your last 30 days
keeb-coach fixes          # get copy-paste aliases for your worst habits
keeb-coach fixes --write ~/.keeb_aliases    # opt-in: persist them
keeb-coach trend          # see how your grade is moving over time
```

### Demo

> Live asciinema/GIF coming with the v0.1 announcement. Until then, here’s
> the flavor of `keeb-coach score` on a real history:

```text
╭───────────────────────────────────────── keeb-coach ──────────────────────────────────────────╮
│ Coach is warming up 🏋️                                              │
│ Detected shell: zsh                                                 │
│ History file:   /home/ryan/.zsh_history                             │
│ Total commands: 1,204 (of 5,890 total, last 30d)                    │
│ Date range:     2026-06-06 09:12 UTC  →  2026-07-06 22:41 UTC       │
╰───────────────────────────────────────────────────────────────────────────────────╯

╭───── Efficiency scorecard ─────╮
│ B   82/100   (1,204 commands)     │
╰────────────────────────────────────────────╯

 Coach’s take
 • missing_alias  You typed `git status` 87 times. You have hands. Alias it.
 • slow_tool      `grep` → `rg`. Get with the program.
 • long_path      That `/home/ryan/projects/big-monorepo/services/api` retype
                    (12×) called; it wants `zoxide` or `cd -`.
```

Want to record your own? `asciinema rec demo.cast` → run `keeb-coach score`
and `keeb-coach fixes` → upload with `asciinema upload demo.cast`.

### What `score` shows today (v0.1)

Right now `keeb-coach score` ingests your bash or zsh history and reports:

- **Total commands** and the timestamp range it saw
- An **efficiency scorecard** with a letter grade (A–F) and per-finding severity
- Findings from the full v0.1 detector set:
  - `missing_alias` — commands you retype often enough to deserve an alias
  - `slow_tool` — `grep`→`rg`, `find`→`fd`, `cat`→`bat`, `ls -la`→`eza`
  - `long_path` — deep `cd` targets you keep retyping instead of `cd -` / `zoxide`
  - `sudo_redo` — the “forgot sudo, retyped the whole thing” classic
- A **Coach's take** section — one witty roast line per weak area
- The **top N commands** by invocation count (`--top N`, default 10)

#### Windowing with `--days`

By default `score` and `fixes` only look at commands **from the last 30 days**
(matching “what did I actually do this month?”). Tune it:

```bash
keeb-coach score --days 7      # this week only
keeb-coach score --days 90     # last quarter
keeb-coach score --days 0      # no window — grade every command in history
```

Commands without a timestamp are always included; otherwise a stock bash
setup without `HISTTIMEFORMAT` would silently score zero.

#### Scripting with `--json`

`keeb-coach score --json` emits a stable, machine-readable scorecard on
stdout — no rich formatting, no roasts. Perfect for `jq`, dashboards, or
a CI gate that fails your build when you slip below a B.

```bash
keeb-coach score --days 7 --json | jq '{grade, score, findings: (.findings|length)}'
# { "grade": "B", "score": 84, "findings": 6 }

# Fail if your grade drops below B this week:
test "$(keeb-coach score --days 7 --json | jq -r .grade)" \
  = "$(printf '%s\n' A B | tail -1)" || exit 1
```

The schema is versioned (`"schema": "keeb-coach.scorecard/v1"`) so future
additions stay backward-compatible.

The M5 `fixes` command turns these findings into copy-paste alias snippets. See below.

### What `fixes` does (M5)

`keeb-coach fixes` prints copy-paste shell snippets — one per finding — that you can drop into your shell or a sourced alias file:

```bash
keeb-coach fixes
# keeb-coach fixes — copy-paste these, or run `keeb-coach fixes --write PATH`.
# Suggested target: ~/.keeb_aliases   (then add `source ~/.keeb_aliases` to your rc)

# missing_alias: retyped `git status` (87×)
alias git_status='git status'

# slow_tool: `grep` → `rg`
alias grep=rg

# long_path: retyped `/home/ryan/projects/foo` — jump alias
alias to_foo='cd /home/ryan/projects/foo'
```

Or, write straight into a dedicated file:

```bash
keeb-coach fixes --write ~/.keeb_aliases
# wrote 3 snippet(s) to /home/ryan/.keeb_aliases
# source it in your shell: `source /home/ryan/.keeb_aliases`
```

Then add `source ~/.keeb_aliases` to your shell rc file once, and re-run `keeb-coach fixes --write` whenever you want to refresh.

**Guarantees:**

- **Idempotent.** Re-running never duplicates entries — the managed block between `# >>> keeb-coach managed block >>>` and `# <<< keeb-coach managed block <<<` is replaced in place.
- **Never touches your rc files.** `--write ~/.bashrc` / `~/.zshrc` / `~/.profile` is refused with a non-zero exit.
- **Preserves surrounding content.** Anything you hand-edit outside the markers survives untouched.
- **Atomic writes.** A crash mid-write cannot leave you with a corrupted alias file.

Point `keeb-coach` at any history file with `$HISTFILE`:

```bash
HISTFILE=~/.zsh_history keeb-coach score
```

### Streaks & progress (`trend`)

Every `keeb-coach score` writes a row into a local SQLite streak DB at
`$XDG_DATA_HOME/keeb-coach/history.db` (defaults to
`~/.local/share/keeb-coach/history.db`). `keeb-coach trend` reads it
back so you can watch your grade move over time.

```bash
keeb-coach trend            # last 14 recorded runs, sparkline + delta
keeb-coach trend --limit 30 # go back further (max 100)
keeb-coach trend --json     # machine-readable, schema v1
```

`score` also prints a one-line trend headline right under the scorecard
when there's a comparable prior run:

```text
Trend: You cut long path findings 60% this week 💪 (5 → 2)
```

The reference run is the most recent one **older than** `--window`
(default 7 days), so "this week vs. last week" still works even when
you only run KeebCoach every few days.

Opt-outs and overrides:

```bash
keeb-coach score --no-record        # grade but don't append to the DB
keeb-coach score --db /tmp/kc.db    # steer both score + trend elsewhere
keeb-coach score --window 14        # compare vs. two weeks ago instead
```

Everything is local: no network, no sync, no daemon. Delete the DB
file and your streak history is gone — no other side effects.

### Configuration

All thresholds are tunable via `~/.config/keeb-coach/config.toml` (or
`$XDG_CONFIG_HOME/keeb-coach/config.toml`). Missing file → defaults.
Broken file → defaults (and no crash). Example:

```toml
[detectors.missing_alias]
min_count = 6      # only nag me about commands I've run 6+ times
min_length = 10

[detectors.slow_tool.replacements]
"grep" = "ugrep"   # override the default suggestion
"top" = "btop"     # add a new slow-tool rule

[detectors.long_path]
min_depth = 4

[detectors.sudo_redo]
min_count = 1      # flag me the very first time I retype
```

Point at an explicit file with `keeb-coach score --config path/to/keeb.toml`.

### Coach personas

The scorecard's roast lines come from a swappable **persona** — pick
the voice that will actually motivate you (or annoy you into fixing
things). Personas are data files, so adding your own is a one-file
change.

List what's available:

```
keeb-coach personas
```

Built-in personas:

- `default` — the original dry, mildly-amused KeebCoach voice.
- `drill_sergeant` — barks orders. Does not care about your feelings.
- `zen_master` — speaks softly. Suggests, never scolds.
- `passive_aggressive_pm` — "just circling back on your keystrokes."

Pick one per run:

```
keeb-coach score --persona drill_sergeant
```

Or set a default in `~/.config/keeb-coach/config.toml`:

```toml
[coach]
persona = "zen_master"
# Optional: a directory of your own <id>.toml persona files.
persona_dir = "~/.config/keeb-coach/personas"
```

Roll your own by dropping a TOML file into `persona_dir` (or passing
its path directly to `--persona`):

```toml
# ~/.config/keeb-coach/personas/surfer.toml
id = "surfer"
name = "Surfer Bro"
description = "Chill, but honest about your keystrokes."

[strings]
takes_header = "Vibes check:"
clean_sheet = "Clean run, dude. Totally stoked."

[roasts.missing_alias]
low  = "Bit repetitive, brah. Alias it, ride the wave."
med  = "You're paddling the same command over and over. Alias it."
high = "Duuude. Alias. It. Now."
```

Missing slots fall through to the default persona, so a minimal file
only has to override the lines you care about.

## Principles

- 🔒 **100% local.** Reads your shell history file. No network, no telemetry, no daemon.
- ✍️ **Opt-in writes only.** We never touch your `.bashrc`. `--write` goes to a separate file you choose to source.
- 🧩 **Pluggable detectors.** New bad-habit detector = one small file.

## Status

🎉 **v0.1.0** — the full v0.1 scope from [`PLAN.md`](./PLAN.md) is shipped:
M1 scaffold, M2 history ingestion, M3 first detectors + scoring, M4
remaining detectors / roasts / config, M5 `fixes` with idempotent managed-
block writes, and M6 polish (`--days`, `--json`, pipx docs, tagged release).

On deck: **v0.2 streaks** — `keeb-coach trend` reads a local SQLite
store of every recorded scorecard so you can watch your grade move
over time.

Next up: the rest of the v0.2 backlog in [`PLAN.md`](./PLAN.md#8-backlog--future-features-v02)
— `watch` mode, more shells, Atuin integration, and coach personas.

## License

MIT
