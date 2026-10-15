# jam

![hero](assets/hero.png)

![status](https://img.shields.io/badge/status-design-blue) ![plugin](https://img.shields.io/badge/Claude%20Code-plugin-D97757)
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

## Design

jam is split into a harness-neutral core and two kinds of adapters, so new
agents and terminal environments can be added later without touching the core.

```text
core            session registry, verbs: spawn / list / stop / whoami
 ├ harness      how a session is started, listed, stopped, and read
 └ environment  seam for terminal-specific delivery (no adapter in v1)
messaging       Claude Code's native SendMessage, taught to the AI by a skill
entry points    MCP server and CLI, both thin wrappers over the same core
```

The first release targets **Claude Code** sessions that are registered with its
background session stack, so they show up in `claude agents`. It does not
depend on a terminal multiplexer. Other harnesses and terminals are out of
scope for now; the adapter seams are there so they can be added when needed.

## Status

Design phase. Nothing is installable yet.

## License

[MIT](LICENSE)
