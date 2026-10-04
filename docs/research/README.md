# Research notes

Dated notes from research done along the way, named `YYYY-MM-DD-topic.md`. Each one is a
snapshot of what was found on that day, kept so we can see when in the project's life a
question was looked at and what was known then. They are not kept current: when the answer
changes, write a new note and link back.

- [2026-10-01 — Tracking what each agent spends](2026-10-01-agent-token-tracking.md): token
  and cost tracking per agent and subagent for Claude Code, Codex and OpenCode; accounts and
  quota; a ledger format safe for many writers; what orchestrators such as Paperclip do; a
  live experiment.
- [2026-10-03 — Structural and entropy review](2026-10-03-structural-review/README.md): the
  composition root as the home of cross-module logic, alternatives to it compared on one
  example, renaming, and the persistence seams the daemon and multiplayer will hit;
  includes an independent Second opinion (Codex).
- [2026-10-04 — Multiplayer: a ladder, coordinated, with git as the only authority](2026-10-04-multiplayer/README.md):
  discussed during the structural review and kept for when multiplayer work starts. Three
  layers (format, git, an advisory coordination service), one set of events with a local and
  a remote transport, the director rule, what still collides in the format, and the failure
  modes to work through. Not designed yet.
