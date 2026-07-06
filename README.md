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

🚧 Early — see [`PLAN.md`](./PLAN.md) and the milestone issues. **M1 scaffold + M2 history ingestion + M3 first detectors & scoring + M4 remaining detectors, roasts, and config + M5 `fixes` command with idempotent managed-block writes shipped.** Next up: M6 (polish + v0.1 release).

## License

MIT
