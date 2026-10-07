# Research notes

Dated notes from research done along the way, named `YYYY-MM-DD-topic.md`. Each one is a
snapshot of what was found on that day, kept so we can see when in the project's life a
question was looked at and what was known then. They are not kept current: when the answer
changes, write a new note and link back.

- [2026-10-01 — Tracking what each agent spends](2026-10-01-agent-token-tracking.md): token
  and cost tracking per agent and subagent for Claude Code, Codex and OpenCode; accounts and
  quota; a ledger format safe for many writers; what orchestrators such as Paperclip do; a
  live experiment.
- [2026-10-01 — Orchestrating agents for playbooks and autonomous workers](2026-10-01-agent-orchestration/README.md):
  how fifteen orchestrators run coding agents, headless CLI flags and auth, hand-back and review
  economics, claims and leases, and a proposal for playbooks and a worker.
- [2026-10-03 — Structural and entropy review](2026-10-03-structural-review/README.md): the
  composition root as the home of cross-module logic, alternatives to it compared on one
  example, renaming, and the persistence seams the daemon and multiplayer will hit;
  includes an independent Second opinion (Codex).
- [2026-10-03 — Playbooks: a chain of agents around one step](2026-10-03-playbooks/README.md):
  self-review against a second agent, the playbook's shape and presets, engine against lead
  agent, failures probed for free against every CLI, and the factory floor; a spike and an
  HTML report.
- [2026-10-04 — Multiplayer: a ladder, coordinated, with git as the only authority](2026-10-04-multiplayer/README.md):
  discussed during the structural review and kept for when multiplayer work starts. Three
  layers (format, git, an advisory coordination service), one set of events with a local and
  a remote transport, the director rule, what still collides in the format, and the failure
  modes to work through. Not designed yet.
- [2026-10-04 — An autonomous run of the arch revision](2026-10-04-autonomous-run/README.md): one
  director session took the 26-step "DPlanner arch revision" plan through 20 step agents and 3
  Codex reviewers in herdr, to a reviewed PR into `main`. A field test of autonomous execution:
  steering counts, bugs found, friction in DPlanner, herdr and Codex, failure modes, and what a
  daemon would need. The effect boundary failed three review rounds, and cross-vendor review earned its cost.
- [2026-10-07 — Headless agents: questions, plan approval, limits and never getting stuck](2026-10-07-headless-agents/README.md):
  eleven small live experiments with Claude Code, Codex and opencode run headless. One question
  door (`dplanner ask`) plus resume works for all three; Claude's native question tool exists
  only when DPlanner hosts it; plan mode is plan → park → resume; nothing blocks headless but
  every CLI fails quietly; both vendors publish limit resets, and a session survives a 429.
