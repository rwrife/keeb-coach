# KeebCoach 🏋️⌨️

**Your terminal has a personal trainer now.** KeebCoach replays your real shell history and grades *how efficiently you type* — then hands you a daily scorecard with a letter grade, your worst habits, and copy-paste fixes.

It's not `thefuck`. It never corrects you live. It watches your patterns over time and coaches you into faster habits — with jokes.

> You typed `git status` 87 times. You have hands. Use `gs`. — Coach

## What it catches (v0.1)

- **Missing aliases** — long commands you run over and over.
- **Long-path retypes** — deep `cd` targets you keep typing instead of `cd -` / `zoxide`.
- **Slow tools** — `grep`→`rg`, `find`→`fd`, `cat`→`bat`, `ls -la`→`eza`.
- **Sudo-redos** — the "forgot sudo, retyped the whole thing" classic.

## Quick start

```bash
pipx install keeb-coach   # (once published)
keeb-coach score          # grade your last 30 days
keeb-coach fixes          # get copy-paste aliases for your worst habits
```

### What `score` shows today (M4)

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

The M5 `fixes` command — which turns these findings into a copy-paste alias file — is next.

Point `keeb-coach` at any history file with `$HISTFILE`:

```bash
HISTFILE=~/.zsh_history keeb-coach score
```

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

## Principles

- 🔒 **100% local.** Reads your shell history file. No network, no telemetry, no daemon.
- ✍️ **Opt-in writes only.** We never touch your `.bashrc`. `--write` goes to a separate file you choose to source.
- 🧩 **Pluggable detectors.** New bad-habit detector = one small file.

## Status

🚧 Early — see [`PLAN.md`](./PLAN.md) and the milestone issues. **M1 scaffold + M2 history ingestion + M3 first detectors & scoring + M4 remaining detectors, roasts, and config shipped.** Next up: M5 (`fixes` command — opt-in alias generation).

## License

MIT
