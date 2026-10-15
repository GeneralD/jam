# jam — Junction for AI Messaging

A Claude Code plugin that lets AI coding agent sessions in different
repositories pass prompts and results to each other. v1 targets Claude Code
sessions registered with its background session stack, and uses the native
`SendMessage` for messaging.

## Read first

- `README.md` — what jam is and the intended architecture.
- `docs/decisions.md` — what was decided, what was rejected, and why. Read it
  before proposing a different design; most alternatives were already weighed.

## How to work

- Official language is **English** for everything in this repo: code,
  comments, docs, commit messages, issues, PRs, and review comments.
  Conversation with the owner may be in their own language.
- Conventional commits. Open PRs as regular (non-draft) PRs, self-assigned,
  and link the issue they close.
- Test: `python3 -m unittest discover -s tests -v`. Stdlib only; write the test
  first and watch it fail. CI runs the same command.
- Validate the manifests: `claude plugin validate --strict .`. It needs the
  Claude Code CLI, so it is a local step and not part of CI.
- Develop with `claude --plugin-dir .` so the working tree is what loads. Do not
  install the plugin into your own settings while developing.
- Code lives in `src/jam/` and is stdlib only. Keep it working on Python 3.9, the
  system `python3` of macOS: no `match`, and no `X | Y` outside annotations
  (`from __future__ import annotations` is in every module).
- `version` lives in `.claude-plugin/plugin.json` only; the marketplace entry
  leaves it out so the two cannot drift.

## Hard rules

- **Install-only.** Installing the plugin must be enough. Nothing outside the
  plugin directory may require a manual edit (settings, PATH, shell config).
  Reason: that is the product promise.
- **No PATH, no hardcoded paths.** The AI learns the CLI location from a
  SessionStart hook that injects the resolved plugin path as
  `additionalContext`. Reason: the plugin cache path changes per version, and
  this repo is public.
- **Core is stdlib-only and harness/environment-agnostic.** Everything specific
  to Claude Code or a terminal lives in an adapter. Reason: later harnesses and
  terminals must not touch the core. v1 has the Claude Code harness adapter
  only; do not add adapters for other harnesses or terminals.
- **Wrap, do not replace, what Claude Code already provides** (`claude --bg`,
  `claude agents --json`, `logs`, `attach`, `stop`, `rm`, and `SendMessage`).
  Reason: a custom socket daemon was considered and rejected as a duplicate of
  the native one.
- **Peers, not a hierarchy.** A spawned session is the owner's session like any
  other and may message its ancestors. Do not model parent and child roles in
  the registry or the protocol, and treat peer messages as input, not orders.
  Reason: see D10 in `docs/decisions.md`.
- **Public repo hygiene.** Never write employer, client, or private repository
  names, usernames, or absolute home paths into any file. Use generic examples.

## State

In-flight state (branch, PR, next action, open questions) lives in Claude
memory, not in this file.
