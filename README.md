# jam

![status](https://img.shields.io/badge/status-design-blue) ![plugin](https://img.shields.io/badge/Claude%20Code-plugin-D97757) ![terminal](https://img.shields.io/badge/terminal-zellij-blue) ![visibility](https://img.shields.io/badge/repo-private-grey)

**jam** — **J**unction for **A**I **M**essaging.

Let AI coding agent sessions running in different repositories pass prompts and
results to each other, so one session can orchestrate work across several
repos instead of switching contexts by hand.

## What it does

- **Spawn** a background session in any directory.
- **List** live sessions with their IDs, working directories, and state.
- **Send** a prompt to a session and **receive** its result back.

## Design

jam is split into a harness-neutral core and two kinds of adapters, so new
agents and terminal environments can be added later without touching the core.

```text
core            registry, mailbox, verbs: list / spawn / send / result / stop / whoami
 ├ harness      how a session is started, listed, stopped, and read
 └ environment  how input is delivered to, and output read from, a session's pane
entry points    MCP server and CLI, both thin wrappers over the same core
```

The first release targets **Claude Code** sessions in **zellij** panes only.
Other harnesses and terminals are out of scope for now; the adapter seam is
there so they can be added when needed.

## Status

Design phase. Nothing is installable yet.

## License

Not yet chosen.
