# jam — Junction for AI Messaging

A Claude Code plugin that lets AI coding agent sessions in different
repositories pass prompts and results to each other. v1 targets Claude Code
sessions in zellij panes only.

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
- No build or test commands exist yet. The first implementation PR defines
  them and updates this section.

## Hard rules

- **Install-only.** Installing the plugin must be enough. Nothing outside the
  plugin directory may require a manual edit (settings, PATH, shell config).
  Reason: that is the product promise.
- **No PATH, no hardcoded paths.** The AI learns the CLI location from a
  SessionStart hook that injects the resolved plugin path as
  `additionalContext`. Reason: the plugin cache path changes per version, and
  this repo is public.
- **Core is stdlib-only and harness/environment-agnostic.** Everything specific
  to Claude Code or zellij lives in an adapter. Reason: later harnesses and
  terminals must not touch the core. Do not add adapters for other harnesses
  or terminals in v1.
- **Wrap, do not replace, what Claude Code already provides** (`claude --bg`,
  `claude agents --json`, `logs`, `stop`, `rm`). Reason: a custom socket
  daemon was considered and rejected as a duplicate of the native one.
- **Public repo hygiene.** Never write employer, client, or private repository
  names, usernames, or absolute home paths into any file. Use generic examples.

## State

In-flight state (branch, PR, next action, open questions) lives in Claude
memory, not in this file.
