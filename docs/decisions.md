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
are thin entry points over the same core. The registry and mailbox live in the
plugin data directory and are disposable (see "Plugin platform facts").

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

## Plugin platform facts

Unless marked as verified, these facts were taken from the official Claude Code
documentation through a research pass and have not been re-verified one by one;
re-check the source before relying on a single claim.

Sources: the plugin
[manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference)
(layout, environment variables, plugin settings, data directory), the
[hooks guide](https://code.claude.com/docs/en/hooks-guide) (hook behavior), and
[installing plugins](https://code.claude.com/docs/en/plugins/install)
(marketplaces, private repositories). The install version requirements were
checked against the release notes for
[2.1.275](https://github.com/anthropics/claude-code/releases/tag/v2.1.275) and
[2.1.292](https://github.com/anthropics/claude-code/releases/tag/v2.1.292).

- **Layout.** `.claude-plugin/plugin.json`, `hooks/hooks.json` (the file needs a
  top-level `"hooks"` key), `.mcp.json`, `skills/`, `bin/`. A plugin `bin/` is
  added to the Bash tool's PATH while the plugin is enabled; jam does not rely
  on it (see D5).
- **Path variables.** `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` are exported
  to hook processes and MCP stdio servers, but not to commands the model runs
  through the Bash tool. This is why a SessionStart hook has to inject the
  resolved path (D5). `CLAUDE_PLUGIN_DATA` survives plugin updates, so the
  registry and mailbox live there instead of a temp directory. Uninstalling the
  plugin from its last scope deletes that directory unless `--keep-data` is
  passed. jam treats this state as disposable: the registry only describes live
  sessions and is rebuilt on the next session start, and a message that was not
  yet delivered when the plugin was removed is dropped. Nothing that must outlive
  an uninstall is stored there.
- **Hooks.** Plugin hooks behave like settings hooks. `additionalContext` must
  be nested in `hookSpecificOutput`; at the top level it is silently ignored.
  A Stop hook can block with `decision: block` but only a limited number of
  consecutive times (check `stop_hook_active`). SessionEnd has a budget of
  about 1.5 seconds, so unregistering must be fast and stale entries are also
  swept at session start.
- **Permissions.** A plugin cannot ship `permissions.allow`; only `agent` and
  `subagentStatusLine` are honored from a plugin's `settings`. The documented
  workaround is a `PermissionRequest` hook that allows the plugin's own MCP
  tools. That is a plugin approving itself, so its matcher must be as narrow as
  possible, or the first-run user approval is kept instead.
- **Install.** The repository carries `.claude-plugin/marketplace.json`. Users
  run `/plugin marketplace add GeneralD/jam`, then `/plugin install` with the
  plugin and marketplace name; this two-step form needs no particular version.
  One-step forms exist too: the in-session `/plugin install <plugin>
  --marketplace <source>` (verified in the 2.1.275 release notes) and the shell
  `claude plugin install <plugin> --marketplace <source>` (the `--marketplace`
  flag was added to the shell command in 2.1.292; the command itself is older).
  Auto-update is off by default for third-party marketplaces. There is no
  install-time hook, so initialization happens lazily on first use.
- **Background sessions (verified by experiment).** The documentation is
  silent, so a throwaway probe plugin was loaded with `--plugin-dir` into both a
  print-mode run (control) and a `claude --bg` session. In both, the plugin's
  stdio MCP server started, and the SessionStart, PostToolUse, and Stop hooks
  fired with `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` exported. So a
  background worker runs jam's hooks and MCP server like any other session.
  Not tested: a plugin installed from a marketplace (the load path is expected
  to be the same).
- **Background sessions need a trusted workspace.** `claude --bg` refuses to
  start in a directory whose workspace trust was never accepted, printing
  "Workspace not trusted. Run `claude` in <dir> once and accept the trust
  prompt, then retry." `spawn` must detect this, stop, and tell the owner
  which directory to trust, instead of retrying or silently failing.

## Open verification items

- zellij `write-chars`: does a trailing carriage return submit the prompt, and
  what happens when written during generation?
- Can a background worker reply to its parent through `SendMessage`?
- Permission prompts for the plugin's MCP tools: `PermissionRequest` hook or
  first-run user approval?
- The exact marketplace name to use in `/plugin install`.

## Not done yet

- License is not chosen.
