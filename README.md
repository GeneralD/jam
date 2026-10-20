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
entry points    MCP server (.mcp.json) and CLI (scripts/jam), one operations table
```

The MCP server is declared in `.mcp.json` and offers `spawn`, `list`, `stop`,
and `whoami` as tools. The CLI is the launcher `scripts/jam`, run as
`python3 -I <plugin root>/scripts/jam <command>`; it is the fallback for when
the tools are not available. Both print the same JSON for the same arguments.
The reasoning is in [docs/decisions.md](docs/decisions.md) (D12).

The first release targets **Claude Code** sessions that are registered with its
background session stack, so they show up in `claude agents`. It does not
depend on a terminal multiplexer. Other harnesses and terminals are out of
scope for now; the adapter seams are there so they can be added when needed.

## Requirements

- Claude Code.
- `python3`, version 3.9 or newer, on the PATH of the Claude Code process. The
  MCP server and the CLI both start with it. On macOS without the developer
  tools, `python3` is a stub that prompts to install them.

## Status

Early development. The plugin installs from this repository and now carries
the MCP server and the CLI with `spawn`, `list`, `stop`, and `whoami`. They are
tested against fakes in place of Claude Code and have not yet been run end to
end in a live session. The hooks and the skill do not exist yet
(`hooks/hooks.json` declares no hooks and there is no `skills/` directory), so
the delegation guard and the `SendMessage` guidance described above are planned,
not shipped.

## License

[MIT](LICENSE)
