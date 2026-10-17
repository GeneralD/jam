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
reports. The harness adapter declares what it can do in v1 (`spawn_bg`, `list`,
`stop`); messaging is the native `SendMessage`, not a jam capability. The
environment seam would declare terminal-specific capabilities (`inject`,
`read_screen`, `wake_idle`) only if an adapter were ever added, and the core
degrades gracefully without them.

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
directory and is disposable (see "Plugin platform facts"). Its shape is D11.

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

Loop protection is required, and the mechanism is still to be designed. An
environment variable set by the spawner does not reach the worker (see Platform
facts), so a depth counter cannot travel that way, and D10 rules out relying on
spawn-chain depth alone. Candidates, undecided: a record the spawner writes
keyed by the worker's short id (the first 8 characters of its `sessionId`) and
read by the worker's hook, or a marker carried in the spawn prompt itself. The
record races: the worker's hook can fire before the spawner has recorded
anything, and D11 does not remove that race. Prefer the marker in the prompt,
unless `claude --bg --session-id` turns out to be honored, which would let the
spawner record before the session starts.

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

Consequences: jam models a flat set of peers, not a tree. jam lists sessions
without a hierarchy, and the registry only annotates the harness's rows (the
spawner's id may be kept as provenance only, see D11),
and `whoami` lets any session learn its own id. A message from a peer is input
to weigh, never an instruction that carries the sender's authority. Loop
protection (D6) cannot rely on a spawn-chain depth alone, because a peer can be
addressed by a session that did not spawn it; it is designed with the guard.

## D11. The session registry

Decided on 2026-10-15, from three independent designs reconciled into one.

- **Shape.** One small JSON file per session, `sessions-v1/<id>.json` under the
  plugin data directory, keyed by the harness's short id (the one `spawn`
  returns; the full `sessionId` would cost another harness call at the one point
  that must not fail). The only field jam reads is `spawned`. Unknown keys are
  kept on every write, so an older writer never erases a newer one's fields. A
  format change renames the directory (`sessions-v2`) instead of adding a
  version field.
- **Harness first.** The harness stays the source of truth for which sessions
  exist. `list` is a left join from harness rows onto notes; a note without a
  row is never shown, and a missing or unreadable note means "unknown", not
  "not spawned by jam".
- **Locking.** Only writes lock. `flock` on a sidecar lock file (not the data
  file, whose inode `os.replace` swaps) is polled against a short deadline,
  because `flock` has no timeout and a blocking wait would hang a hook. The
  write goes to a temp file in the same directory and is renamed over the note;
  there is no fsync because the data is disposable. Reads, `remove`, and `prune`
  take no lock, and the lock is never held while the harness spawns.
- **Failure.** Damaged, oversized, or wrongly typed content reads as "no note"
  and the next update overwrites it. An OS error (permissions, I/O) is never
  treated as an absence: it raises `RegistryError`, which is not a
  `HarnessError`, carries no path, and never leads to an overwrite. A spawn that
  succeeded never raises because of the registry: `Jam.spawn` returns the id
  together with a `problem` text, so a caller is not tempted to respawn.
- **Sweeping.** By file age only (30 days), not against the harness listing:
  whether foreground sessions appear in `claude agents` is unverified, and a
  listing-based sweep could delete the notes of live sessions the listing does
  not show. The SessionStart hook is to call `prune`. `remove` exists; whether
  SessionEnd calls it is left to the hooks work (recommended: no, because a
  stopped session stays in the full listing and a resumed one returns with the
  same id).
- **Platform.** macOS and Linux (`fcntl`), local filesystem only. The data
  directory and its subdirectory are created 0700 (the notes 0600), whatever the
  umask, so another local user cannot replace them.
- **Not stored, on purpose.** The spawner's id (no reader, and nothing can write
  it yet), the working directory, the full session id, and timestamps (the
  file's modification time is the clock for `prune`). Each is added by the change
  that brings its reader.
- **Not solved here.** D6: `spawned` is recorded after the spawn returns, so a
  worker's first hook can run before the note exists.

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
  treats this state as disposable: the registry holds only jam's own notes about
  sessions (today, which ones jam spawned), while the harness stays the source of
  truth for which sessions exist. Losing a note costs only its annotation, though
  a lost `spawned` note cannot be rebuilt from the harness. Nothing that must
  outlive an uninstall is stored there.
- **Hooks.** Plugin hooks behave like settings hooks. `additionalContext` must
  be nested in `hookSpecificOutput`; at the top level it is silently ignored.
  A Stop hook can block with `decision: block` but only a limited number of
  consecutive times (check `stop_hook_active`). SessionEnd has a budget of
  about 1.5 seconds, so nothing slow may run there: the registry's reads and
  `remove` take no lock and start no subprocess, and stale notes are swept by
  age (`prune`) rather than at the end of a session.
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
  which directory to trust, instead of retrying or silently failing. Observed:
  the command exits with status 1, writes the message to stderr, names the
  resolved path, and starts no session. A fresh temporary directory outside
  the owner's config was refused, while a new subdirectory under a directory
  that holds a trusted project was accepted, so trust may be inherited from an
  ancestor (unverified). jam therefore does not pre-check trust: it runs the
  command and reacts to the error.
- **Environment variables do not reach `--bg` workers (verified by
  experiment).** A variable set on the shell that runs `claude --bg` was absent
  in the worker: asked to run `printenv` on it through its Bash tool, the
  worker answered that it was unset. Workers are started by the supervisor
  from a pre-warmed pool, not from the spawning shell. Anything a worker must
  know has to travel in the prompt or in a file.
- **Background session commands (observed on 2.1.300).** `claude --bg [-n
  name] [--permission-mode mode] -- <prompt>` prints `backgrounded · <id> ·
  <name>` (with terminal colors) and exits 0; the `--` makes a prompt that
  starts with a dash safe. The id is the first 8 characters of `sessionId`.
  `claude agents --json` rows have `id`, `sessionId`, `name`, `cwd`, `kind`,
  `startedAt`, `state`, and, while the session runs, `pid` and `status`
  (`busy` or `idle`). `claude stop` removes a session from that plain listing
  at once; with `--all` the row stays, without `pid` or `status`, until
  `claude rm`, after which it is gone from both. The `state` seen right after
  a stop was `stopped` in two runs and `done` in a third, so it is treated as
  a pass-through string. The help text says the plain listing also includes
  interactive sessions, but only background ones have been seen. A session's
  transcript is a JSONL file in the project directory named after its
  `sessionId`; `claude logs` shows only a terminal redraw.
- **Install from the public repository (verified by experiment).** With the
  manifests on `main`, `claude plugin marketplace add GeneralD/jam` registered
  a marketplace named `jam` and `claude plugin install jam@jam` installed the
  plugin at version 0.1.0 in user scope, enabled. `claude plugin uninstall
  jam@jam` followed by `claude plugin marketplace remove jam` restored the plugin
  and marketplace lists to exactly what they were before. Two details: because
  the plugin source is the repository root (`./`), the installed copy is the
  whole repository (docs, tests, and assets included, under 1 MB for now), and
  uninstalling leaves the cached copy on disk. If the payload grows, move it to
  a subdirectory and point the marketplace entry at it.

## Open verification items

- Peers hold a message for approval when permission modes differ. Which
  permission mode should `spawn` give a worker so that messages flow without
  a prompt?
- `claude stop` followed by `claude rm` once printed success while the session
  stayed in `claude agents` as idle; a second stop and rm removed it. It did
  not reproduce in five later runs, and the adapter does not retry: `remove`
  checks the full listing and reports a session that is still there.
- Interactive (foreground) sessions: do they appear in `claude agents --json`,
  and can a worker's message wake one?
- Does `claude --bg --session-id <uuid>` keep the id it is given? If so, the
  spawner can write a note before the session starts, which closes the race in
  D6. It needs a real spawn in a trusted directory to find out.
