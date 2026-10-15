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

## D2. Messaging uses the native `SendMessage`

Revised on 2026-10-15; the original design is kept below as the fallback.

Decided: sessions talk to each other through Claude Code's own `SendMessage`
instead of a jam-owned transport. Verified by experiment between this
orchestrating session and a `claude --bg` worker:

- parent to an idle worker: the message wakes the worker;
- worker to a running parent: the message arrives mid-turn as a
  `<cross-session-message>`;
- worker to an idle parent: the message wakes the parent.

Delivery goes through a per-session Unix socket that the harness manages. Peers
hold a message for approval when their permission modes differ. The roles above
(parent, worker) only describe who started whom in the experiment; see D10.

**Caveat.** In the experiment the receiving parent was itself a
`kind: background` session. Not verified: a foreground terminal session (a
plain terminal or a zellij pane) being woken by a worker's message. The owner
decided that this does not matter: jam only needs participating sessions to be
registered with Claude Code's background session stack (see D4).

Original design, now the fallback: delivering a prompt to a live session means
writing to its pseudo-terminal, and reading a result means reading its screen.
Screen text is messy, so results would travel through a file mailbox instead.

| Terminal owner | Write | Read |
|---|---|---|
| Claude Code daemon (background sessions) | attach / daemon pty socket | `claude logs` |
| zellij (interactive sessions) | `zellij action write-chars --pane-id` | `zellij action dump-screen --pane-id` |

## D3. Hook delivery by session state is deferred

Superseded by D2: the native messaging already covers a busy, a mid-turn, and
an idle receiver among sessions registered with the background stack, so jam
does not build a mailbox or the hook delivery below in v1. This table would
return only if native messaging proves insufficient for a registered session.

| Session state | Delivery |
|---|---|
| Busy | PostToolUse hook reads the mailbox and injects it as `additionalContext` |
| About to stop | Stop hook reads the mailbox and continues with `decision: block` |
| Idle | Hooks do not run; wake it by writing to its zellij pane (**unverified**: whether a trailing carriage return submits the prompt) |

## D4. Scope: Claude Code first, behind adapter seams

Decided on 2026-10-15 (native-first).

Core is a session registry plus the verbs `spawn`, `list`, `stop`, and `whoami`
(the exact set is settled in the skeleton PR). It is stdlib-only and knows
nothing about a harness or a terminal. `send` and `result` are not jam verbs in
v1: the skill teaches the AI to use the native `SendMessage` with the ids jam
reports. A harness adapter and an environment seam each declare capabilities
(`spawn_bg`, `inject`, `read_screen`, `wake_idle`) and the core degrades
gracefully.

v1 ships only the Claude Code harness adapter and no environment adapter. jam
does not depend on a terminal multiplexer: it works for sessions that are
registered with Claude Code's background session stack (visible in
`claude agents`). A session that is not registered there is out of scope for
v1, and the README states that requirement.
The environment seam stays so that a zellij adapter can be added later without
touching the core, but it is not planned. Codex and other harnesses are out of
scope.

## D5. Plugin, installed with nothing else

The repository is its own marketplace. The MCP server, hooks, and skill ship in
one plugin. The AI is told the CLI's absolute path by a SessionStart hook
(`additionalContext`), so no PATH change is needed. The MCP server and the CLI
are thin entry points over the same core. The registry lives in the plugin data
directory and is disposable (see "Plugin platform facts").

## D6. Automatic delegation guard

A PreToolUse hook on Edit, Write, MultiEdit, and NotebookEdit fires when the
target file is in a repository other than the one the session started in
(worktrees of the same repository, the start directory, non-git paths, and
gitignored files are excluded). It denies once per (session, repository) with a
reason pointing to jam delegation; the re-issued edit passes. Rationale: relying
on the model to remember to use the tool did not work in a comparable
canvas-based setup, while a hook fires on the event itself. Not forced on every
edit, so legitimate direct edits are never blocked.

Why delegate at all: a session started in the other repository loads that
repository's own `.claude` instructions, rules, skills, and hooks into its
context, so the work follows the local conventions. An edit made from outside
never sees them. Orchestrating work across repositories this way is the main
benefit of jam, and the guard exists to make it the default path.

Limits: shell writes (`sed -i`, `git -C`, redirects) are not detected in v1.
A delegation depth cap is required to prevent delegation loops.

## D7. Name

`jam`, expanded as "Junction for AI Messaging". The name mentions neither a
harness nor a terminal so adapters can be added later.

## D8. MCP tools are approved by the user on first use

Decided on 2026-10-15: jam does not ship a `PermissionRequest` hook that
approves its own MCP tools. The owner approves them once on first use.
Rejected: the auto-allow hook. A plugin granting itself permission is a
self-grant that the user did not make, and the cost it would save is one prompt.

## D9. License

MIT, chosen by the owner on 2026-10-15. The text is in `LICENSE`.

## D10. Sessions are peers

Decided on 2026-10-15. Once a session is started, the session that spawned it
and the spawned session are equals. The owner keeps instructing the spawned
session directly, as with any session, and a spawned session may message any of
its ancestors on its own initiative, not only reply to its spawner.

Consequences: jam models a flat set of peers, not a tree. The registry lists
sessions without a hierarchy (the spawner's id may be kept as provenance only),
and `whoami` lets any session learn its own id. A message from a peer is input
to weigh, never an instruction that carries the sender's authority. Loop
protection (D6) cannot rely on a spawn-chain depth alone, because a peer can be
addressed by a session that did not spawn it; it is designed with the guard.

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
  registry lives there instead of a temp directory. Uninstalling the plugin from
  its last scope deletes that directory unless `--keep-data` is passed. jam
  treats this state as disposable: the registry only describes live sessions and
  is rebuilt on the next session start. Nothing that must outlive an uninstall
  is stored there.
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

- Does an environment variable set on the spawning shell (a delegation depth
  counter, for example) reach a `--bg` worker? Workers are started by the
  supervisor and may not inherit it.
- Peers hold a message for approval when permission modes differ. Which
  permission mode should `spawn` give a worker so that messages flow without
  a prompt?
- `claude stop` followed by `claude rm` once printed success while the session
  stayed in `claude agents` as idle; a second stop and rm removed it. Cleanup
  must re-list to confirm.
- The exact marketplace name to use in `/plugin install`.
