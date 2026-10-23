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
- **Guard** against editing another repository directly: the first such edit in
  a session is denied once with a pointer to delegation, and the re-issued edit
  passes.

## Why delegate instead of editing directly

A session started in a repository loads that repository's own `.claude`
instructions, rules, skills, and hooks. Work delegated there follows the local
conventions, while an edit made from another repository follows that session's
setup, which may not include them. jam makes delegation the default path for
cross-repo work.

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

Three SessionStart hooks run through the same launcher (`scripts/jam hook ...`):
one injects a short notice that gives the model the exact command line, with the
data directory flag; one records where the session started and, at a fresh
start, when `spawn` left a ticket for that directory in the last 300 seconds,
turns the ticket into the session's worker mark (D14); and the third sweeps
stale session notes, guard files and spawn tickets at startup. They never block
a session: a failure they can handle still exits 0, and one that hangs is ended
by an alarm (D13). A PreToolUse hook, the delegation guard, runs through the
same launcher before an edit (`Edit`, `Write`, `MultiEdit` or `NotebookEdit`).
Once per session and repository, it denies an edit of a file in a repository
other than the one the session started in, with a reason that points to
delegation; D14 lists the exceptions, among them a session with a worker mark.
For any other edit it prints nothing, so the normal permission flow decides.

The first release targets **Claude Code** sessions that are registered with its
background session stack, so they show up in `claude agents`. It does not
depend on a terminal multiplexer. Other harnesses and terminals are out of
scope for now; the adapter seams are there so they can be added when needed.

## Requirements

- Claude Code.
- `python3`, version 3.9 or newer, on the PATH of the Claude Code process. The
  MCP server, the CLI and the hooks all start with it. On macOS without the
  developer tools, `python3` is a stub that prompts to install them.

## Install

In a Claude Code session, version 2.1.275 or later:

```text
/plugin install jam --marketplace GeneralD/jam
```

On an older version, add the marketplace first, then install from it:

```text
/plugin marketplace add GeneralD/jam
/plugin install jam@jam
```

Nothing else is set up by hand: no PATH change and no settings edit (D5).

## Status

Early development. The plugin installs from this repository and carries the MCP
server and the CLI with `spawn`, `list`, `stop`, and `whoami`, plus three
SessionStart hooks: the notice that tells the model how to run jam, the step
that records the start directory and, at a fresh start, turns a spawn ticket
from the last 300 seconds into a worker mark, and the startup sweep of stale
notes, guard files and spawn tickets. It also carries the delegation guard, a
PreToolUse hook on the four edit tools. All of it is tested against fakes in
place of Claude Code. A print-mode session with `claude -p --plugin-dir .`
connected the MCP server, answered `list` through it, and ran the notice. The
one check left to the owner is an interactive `claude --plugin-dir .` session,
started in a trusted directory and not as a background session (`--bg`). The
guard's design is accepted (D14), and the live checks it waited for ran in real
background sessions on 2026-10-21, among them a background worker taking its
mark; it was registered once the owner approved the text the model reads
(D14-8). The `delegate` skill (`/jam:delegate`) teaches the model when to
delegate, how to brief a worker, and how to wait for it and exchange messages
with it through `SendMessage` (D15). On 2026-10-24 the acceptance criteria were
checked end to end on Claude Code 2.1.309 (see "Acceptance check" in
`docs/decisions.md`).

## License

[MIT](LICENSE)
