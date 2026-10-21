# jam

![hero](assets/hero.png)

![status](https://img.shields.io/badge/status-early%20development-yellow) ![plugin](https://img.shields.io/badge/Claude%20Code-plugin-D97757)
**jam** — **J**unction for **A**I **M**essaging.

Let AI coding agent sessions running in different repositories pass prompts and
results to each other, so one session can orchestrate work across several
repos instead of switching contexts by hand.

## What it does

- **Spawn** a background session in any directory.
- **List** live sessions with their IDs, working directories, and state.
- **Send** a prompt to a session and **receive** its result back, using Claude Code's
  native `SendMessage`.
- Treat every session as a **peer**: a spawned session still takes instructions
  from the owner as usual and may message the sessions that started it.
- **Guard** against editing another repository directly: the first such edit in a
  session is denied once with a pointer to delegation, and the re-issued edit passes.
  Planned: the core is built and tested but not registered yet (see Status).

## Why delegate instead of editing directly

A session started in a repository loads that repository's own `.claude`
instructions, rules, skills, and hooks. Work delegated there follows the local
conventions, while an edit made from another repository never sees them. jam
makes delegation the default path for cross-repo work.

## Design

jam is split into a harness-neutral core and two kinds of adapters, so new
agents and terminal environments can be added later without touching the core.

```text
core            session registry, verbs: spawn / list / stop / whoami
 ├ harness      how a session is started, listed, stopped, and read
 └ environment  seam for terminal-specific delivery (no adapter in v1)
messaging       Claude Code's native SendMessage, taught to the AI by a skill
entry points    MCP server (plugin.json) and CLI (scripts/jam), one operations table
```

The MCP server is declared inline in `.claude-plugin/plugin.json` and offers
`spawn`, `list`, `stop`, and `whoami` as tools. The CLI is the launcher
`scripts/jam`, run as `python3 -I <plugin root>/scripts/jam <command>`; it is
the fallback for when the tools are not available. Both print the same JSON for
the same arguments. The reasoning is in [docs/decisions.md](docs/decisions.md)
(D12).

Two SessionStart hooks run through the same launcher (`scripts/jam hook ...`):
one injects a short notice that gives the model the exact command line, with the
data directory flag, and the other sweeps stale session notes and stale guard
files at startup. They never block a session: a failure they can handle still
exits 0, and one that hangs is ended by an alarm (D13). A third hook, the
delegation guard, is implemented and tested but not registered, so no session
reaches it yet (D14).

The first release targets **Claude Code** sessions that are registered with its
background session stack, so they show up in `claude agents`. It does not
depend on a terminal multiplexer. Other harnesses and terminals are out of
scope for now; the adapter seams are there so they can be added when needed.

## Requirements

- Claude Code.
- `python3`, version 3.9 or newer, on the PATH of the Claude Code process. The
  MCP server, the CLI and the hooks all start with it. On macOS without the
  developer tools, `python3` is a stub that prompts to install them.

## Status

Early development. The plugin installs from this repository and carries the MCP
server and the CLI with `spawn`, `list`, `stop`, and `whoami`, plus two
SessionStart hooks: the notice that tells the model how to run jam, and the
startup sweep of stale notes and guard files. All of it is tested against fakes
in place of Claude Code. A print-mode session with `claude -p --plugin-dir .`
connected the MCP server, answered `list` through it, and ran the notice. The
one check left to the owner is an interactive `claude --plugin-dir .` session,
started in a trusted directory and not as a background session (`--bg`). The
core of the delegation guard exists and is tested, but it is not registered:
`hooks/hooks.json` declares only the two SessionStart hooks, so no session is
affected. Its design is accepted (D14); registering it waits for live checks in
real sessions, and for the change that marks the sessions jam starts. The skill
does not exist yet (there is no `skills/` directory), so the `SendMessage`
guidance described above is planned, not shipped.

## License

[MIT](LICENSE)
