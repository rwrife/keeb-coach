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

### What `score` shows today (M2)

Right now `keeb-coach score` ingests your bash or zsh history and reports:

- **Total commands** and the timestamp range it saw
- The **top 10 commands** by invocation count

Detectors, letter grade, and the roast lines all land in M3+. Point `keeb-coach` at any history file with `$HISTFILE`:

```bash
HISTFILE=~/.zsh_history keeb-coach score
```

## Principles

- 🔒 **100% local.** Reads your shell history file. No network, no telemetry, no daemon.
- ✍️ **Opt-in writes only.** We never touch your `.bashrc`. `--write` goes to a separate file you choose to source.
- 🧩 **Pluggable detectors.** New bad-habit detector = one small file.

## Status

🚧 Early — see [`PLAN.md`](./PLAN.md) and the milestone issues. **M1 scaffold + M2 history ingestion (bash + zsh) shipped.** Next up: M3 (first detectors + scoring skeleton).

## License

MIT
