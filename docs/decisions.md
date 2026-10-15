# Decisions

Newest information wins; each entry says what was decided, why, and what was
rejected. Items marked **unverified** are assumptions to confirm before relying
on them.

## D1. Build on the native background-session stack

Decided: wrap Claude Code's own background sessions instead of writing a socket
daemon.

Verified on Claude Code 2.1.284: `claude --bg` starts a background session,
`claude agents --json` lists live sessions (id, cwd, kind, status), and
`claude logs|attach|stop|rm <id>` manage them. The built-in daemon already owns
each background session's pseudo-terminal and uses Unix sockets internally.

Rejected: a custom socket daemon. It would duplicate the native one and depend
on its own protocol staying in sync.

## D2. Whoever owns the terminal can inject input

Delivering a prompt to a live session means writing to its pseudo-terminal, and
reading a result means reading its screen. Screen text is messy, so results
travel through a file mailbox instead.

| Terminal owner | Write | Read |
|---|---|---|
| Claude Code daemon (background sessions) | attach / daemon pty socket | `claude logs` |
| zellij (interactive sessions) | `zellij action write-chars --pane-id` | `zellij action dump-screen --pane-id` |

There is no native CLI to send a prompt to a running interactive session.

## D3. Delivery depends on session state

| Session state | Delivery |
|---|---|
| Busy | PostToolUse hook reads the mailbox and injects it as `additionalContext` |
| About to stop | Stop hook reads the mailbox and continues with `decision: block` |
| Idle | Hooks do not run; wake it by writing to its zellij pane (**unverified**: whether a trailing carriage return submits the prompt) |

## D4. Scope: Claude Code x zellij, behind adapter seams

Core (registry, mailbox, verbs `list`, `spawn`, `send`, `result`, `stop`,
`whoami`) is stdlib-only and knows nothing about a harness or a terminal. A
harness adapter and an environment adapter each declare capabilities
(`spawn_bg`, `inject`, `read_screen`, `wake_idle`) and the core degrades
gracefully. Only the Claude Code and zellij adapters exist in v1. Codex and
others are out of scope for now.

## D5. Plugin, installed with nothing else

The repository is its own marketplace. The MCP server, hooks, and skill ship in
one plugin. The AI is told the CLI's absolute path by a SessionStart hook
(`additionalContext`), so no PATH change is needed. The MCP server and the CLI
are thin entry points over the same core.

## D6. Automatic delegation guard

A PreToolUse hook on Edit, Write, MultiEdit, and NotebookEdit fires when the
target file is in a repository other than the one the session started in
(worktrees of the same repository, the start directory, non-git paths, and
gitignored files are excluded). It denies once per (session, repository) with a
reason pointing to jam delegation; the re-issued edit passes. Rationale: relying
on the model to remember to use the tool did not work in a comparable
canvas-based setup, while a hook fires on the event itself. Not forced on every
edit, so legitimate direct edits are never blocked.

Limits: shell writes (`sed -i`, `git -C`, redirects) are not detected in v1.
A delegation depth cap is required to prevent delegation loops.

## D7. Name

`jam`, expanded as "Junction for AI Messaging". The name mentions neither a
harness nor a terminal so adapters can be added later.

## Open verification items

- zellij `write-chars`: does a trailing carriage return submit the prompt, and
  what happens when written during generation?
- Can a background worker reply to its parent through `SendMessage`?
- Do plugin hooks and plugin MCP servers run inside `--bg` sessions?
- Can a plugin's MCP tools be preapproved to avoid permission prompts?
- Private or public repo as its own marketplace: exact install commands.

## Not done yet

- License is not chosen.
