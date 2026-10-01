# The landscape: how open-source orchestrators run coding agents

*Gathered 2026-10-01. The code of six projects was read through the GitHub API (contents, trees, code search). Star counts and last-push dates are that day's. Paths in the per-project sections are inside each project's repository.*

## At a glance

| Project | Repo | Stars | State on 2026-10-01 |
|---|---|---|---|
| Paperclip | `paperclipai/paperclip` (TS) | 95.7k | Very active; CVSS 10 RCE CVEs in Aug 2026 |
| Spec Kit | `github/spec-kit` | 139.7k | Active; a planning toolkit, not an orchestrator |
| ruflo (ex claude-flow) | `ruvnet/ruflo` | 73.6k | Active; heavily criticised (see below) |
| Vibe Kanban | `BloopAI/vibe-kanban` (Rust) | 28.2k | Sunset announced 2026-04-10; community-maintained |
| Beads | `gastownhall/beads` (Go) | 27.6k | Very active |
| OpenAI Symphony | `openai/symphony` (Elixir + `SPEC.md`) | 27.5k | Active |
| Gas Town | `gastownhall/gastown` (Go) | 18.2k | Yegge's Aug 2026 essay says it "burned down"; successor "Wheelhouse" is private, still on Beads |
| Agent Orchestrator ("AO", ex Composio) | `Untrivial-ai/agent-orchestrator` (Go) | 12.6k | Very active |
| Claude Squad | `smtg-ai/claude-squad` | 8.6k | Maintenance |
| takt | `nrslib/takt` | 1.4k | Active; YAML "agent coordination topology" |
| Agent Farm | `Dicklesworthstone/claude_code_agent_farm` | 920 | Shell + tmux |
| Sculptor (Imbue) | `imbue-ai/sculptor` | 233 | Research preview |
| ccswarm | `nwiizo/ccswarm` (Rust) | 153 | Small, but the closest thing to a playbook |
| Terragon | `terragon-labs/terragon-oss` | 259 | Service shut down 2026-02-09; code open |
| Conductor (Melty Labs) | — | — | Closed-source Mac app; worktrees + parallel Claude/Codex |

The two closed references for server-side autonomous workers, Devin and Factory's droids, were not checked in code.

## OpenAI Symphony: the closest model for an autonomous worker

Sources: [SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md), `elixir/WORKFLOW.md`, `elixir/lib/symphony_elixir/config/schema.ex`.

- **Launch.** One `bash -lc "codex app-server"` subprocess per issue, in a workspace directory of its own, driven over the app-server's JSON-RPC on stdio (SPEC §10.1). Remote workers are the same command over SSH stdio (Appendix A); the orchestrator stays the only authority on claims.
- **Completion.** The protocol's turn-completed, turn-failed or cancelled event. A turn also fails on `turn_timeout_ms` (default 1 h), on a stall (no event for `stall_timeout_ms`, default 5 min) or when the process exits.
- **Hand-back.** Symphony calls itself only "a scheduler/runner and tracker reader" (§1). The agent does every ticket write (state, comments, PR links) through tracker tools the orchestrator injects (`linear_graphql`). The orchestrator holds the credential, and the child sees only tool results (§11.5).
- **Memory across runs** is **one persistent "## Codex Workpad" comment** on the issue, rewritten rather than appended. Inside one run, continuation turns reuse the **same thread** and send only "continuation guidance", up to `max_turns` (default 20) (§7.1, §10.2).
- **Review.** It is human-driven through tracker states: `Todo → In Progress → Human Review → Rework → Merging → Done`. In `Rework` the agent "run[s] full PR feedback sweep, address or explicitly push back". There is no AI reviewer and no round cap, only retries with backoff `min(10s·2^(n-1), 5m)` (§8.4).
- **Claims** are held **in memory** by the single orchestrator (`claimed` and `running` maps). There is no database: a restart rebuilds state from the tracker and the filesystem (§7.4, §14.3). Each tick, reconciliation stops runs whose issue has left the active states.
- **Policy** lives in the repository as `WORKFLOW.md`, YAML front matter plus a Liquid prompt, and is hot-reloaded.
- **Budget.** Only concurrency limits (global and per state), `max_turns` and timeouts. Tokens are counted (§13.5) but nothing caps them.
- **Reported failures.** Token and retry storms at scale ($3–8 per attempt on large issues), and lock-in to Linear ([Better Stack](https://betterstack.com/community/guides/ai/openai-symphony/), [Vaughan](https://codex.danielvaughan.com/2026/04/28/openai-symphony-codex-orchestration-linear-autonomous-agent-workflows/)).

**For DPlanner:** the plan is the tracker. Symphony's shape — a dumb scheduler that reconciles each tick, with the agent writing status through tools — is what `AutoLauncher` already is, minus the window.

## Beads and Gas Town: a git-synced tracker and a tmux factory

Sources: [beads](https://github.com/gastownhall/beads) (`cmd/bd/reclaim.go`, `internal/storage/dolt/issue_claimer.go`), [gastown](https://github.com/gastownhall/gastown) (`docs/design/*.md`, `internal/formula/formulas/*.toml`).

### Beads — the part most like DPlanner

- **Storage left plain git files.** It began as SQLite plus `issues.jsonl` committed to git, and moved to Dolt: embedded (one writer) or `dolt sql-server` (many writers). Machines sync with `bd dolt push/pull` against `refs/dolt/data` **on the same git remote**. `.beads/issues.jsonl` is now an export only, and Gas Town calls it "used only for disaster-recovery backups" (`docs/design/dolt-storage.md`). Hash ids (`bd-a1b2`) avoid collisions across branches. *They gave up on merging plain files in git for a hot, many-writer claim store.*
- **A claim is a compare-and-set inside a transaction, re-read after the write.** The comment in `issue_claimer.go` explains why: "under a degraded server the write's exit status is not truth in either direction, and a phantom claim is a duplicated implementation". The verbs are `bd ready` (unblocked work) → `bd update <id> --claim` (assignee + in_progress) → `bd close`.
- **A stale claim is a lapsed lease.** `bd heartbeat` keeps one alive, and `bd reclaim --older-than` is the reaper that resets lapsed ones to open. Grace should be about 2× the TTL, and both must be longer than the replica sync interval. **A lease records the replica that granted it, and a reaper skips leases another replica granted** (`cmd/bd/reclaim.go`). This is directly the problem of a server worker and a laptop both claiming.

### Gas Town

- **Launch.** Every agent is a tmux session, driven with `send-keys`. Its own docs call this "the tmux shim layer — it works but is timing-sensitive" (`docs/agent-provider-integration.md`). Per-agent presets hold `resume_flag`, `prompt_flag: -p`, `ready_prompt_prefix` (it polls the prompt to tell when an agent is ready) and `process_names` (liveness). Tier-2 agents get lifecycle hooks, and the SessionStart hook runs `gt prime`.
- **Assignment.** Work is "hooked" onto an agent, and the "Propulsion Principle" tells it: "If you find something on your hook, YOU RUN IT."
- **Completion is a CLI verb.** `gt done` checks the tree is clean, pushes the branch, creates a merge-request bead, writes completion metadata on the agent's bead and nudges the next role (`docs/design/polecat-self-managed-completion.md`).
- **Mail** is beads of `type=message` (POLECAT_DONE, MERGE_READY, MERGED; `docs/design/mail-protocol.md`), plus tmux nudges.
- **Plans as data.** "Formulas" and "molecules" are TOML DAGs whose steps declare `needs = [...]`. `mol-polecat-work.formula.toml` runs load-context → branch → implement → commit → self-review → build-check → pre-verify → submit. `code-review.formula.toml` is a "convoy" that fans out up to ten reviewer legs in parallel and adds a synthesis step. Routing a model per step is still "In Progress" (`docs/design/model-aware-molecules.md`).
- **Review.** Self-review, a parallel convoy review, then the Refinery merge queue. There is no fixed fix→re-review count.
- **Reported failures.**
  - About $100/h at peak and $3,000 in one week. Polecats committed straight to main. A "murderous rampaging Deacon". Force-pushes to recover ([DoltHub](https://www.dolthub.com/blog/2026-03-24-a-week-in-gas-town/), [Maggie Appleton](https://maggieappleton.com/gastown)).
  - The Witness patrol loop became a serial bottleneck that left zombie "done" polecats (the design doc above).
  - In Aug 2026 Yegge wrote that Gas Town "effectively burned down" because a model's "just two more things" habit stopped work from converging. The successor is "yet another Beads machine", with atomic claims and cross-model review: "Fable design, Opus implementation, Fable review" ([essay](https://yegge.ai/essays/the-shape-of-things-to-come/), [Latent Space](https://www.latent.space/p/ainews-reality-checks-on-ai-news)).

## Paperclip: a server database, heartbeats and session resume

Sources: `doc/spec/agent-runs.md`, `doc/SPEC-implementation.md`, `skills/paperclip/SKILL.md`, `packages/adapters/claude-local/src/server/execute.ts`, `docs/guides/board-operator/costs-and-budgets.md` in [paperclipai/paperclip](https://github.com/paperclipai/paperclip).

- **Launch.** Agents run in "heartbeats": short runs started by a timer, by an assignment, on demand or by a comment. The `claude_local` adapter runs `claude --print --output-format stream-json --verbose [--resume <sessionId>] --model … --max-turns N --append-system-prompt-file …` (`execute.ts` ~849–870).
- **Completion** is the process exit plus the parsed stream-json result. The session id and usage are kept per agent, so **the next heartbeat resumes the same session**. If the working directory changed it does not resume, and an unknown session falls back to a fresh one.
- **Communication.** Agents call the REST API with a short-lived run JWT, and send `X-Paperclip-Run-Id` on every mutation (checkout, comment, subtask, release).
- **Review feedback goes into the original session.** A comment wakes the assignee with `PAPERCLIP_WAKE_COMMENT_ID`, and the new comments are **inlined into the resumed session's prompt**.
- **Claims.** `POST /api/issues/{id}/checkout` with `expectedStatuses` answers 409 when another agent holds the issue, and the skill tells the agent "**Never retry a 409**". The lock columns are `checkout_run_id`, `execution_run_id` and `execution_locked_at`. The watchdog recovers dead runs and "never replay[s] tool calls automatically".
- **Review.** Status `in_review` carries `review_policy: anyone | not_creator | human_only`, and a verdict is checked against the policy under a row lock. Human approvals and "Ask first" tool gates wait in a server outbox.
- **State** is PostgreSQL (embedded by default). It is multi-company and server-first.
- **Budget, the best in the field:** monthly cents per company and per agent. It warns at 80% and **pauses automatically at 100%** ("no more heartbeats"), with incident tables.
- **Reported failures.**
  - An enormous surface: the docs carry dozens of revisions of the chat-adapter plan (v5–v8).
  - Ritual "acknowledge the latest comment" turns.
  - CVE-2026-41679 (CVSS 10): unauthenticated remote code execution through agent imports and the default trusted local mode ([The Hacker News](https://thehackernews.com/2026/08/paperclip-ai-flaws-let-attackers-run.html), [CSO](https://www.csoonline.com/article/4205630/critical-paperclip-bugs-expose-ai-agent-trust-failures.html)).

## Agent Orchestrator: a reviewer from another harness, fed into the worker's session

Sources: `backend/internal/lifecycle/reactions.go`, `backend/internal/service/review/review.go`, `backend/internal/skillassets/using-ao/commands/review.md` in [Untrivial-ai/agent-orchestrator](https://github.com/Untrivial-ai/agent-orchestrator).

- **Launch.** A local daemon plus a desktop app. Each worker gets a worktree and a branch and runs its agent's own terminal UI (tmux, `internal/tmuxbin`) or a "structured Chat". It supports 32 harnesses.
- **The review loop is the closest to a DPlanner playbook:**
  - The reviewer is **a separate agent session with its own harness**. `SwitchReviewer(harness)` makes it, say, Codex while the worker is Claude.
  - The reviewer reports through **a CLI verb**: `ao review submit <worker> --run <id> --verdict approved|changes_requested --body - [--review-id <gh id>]`. The verb is idempotent and retries for 30 s across a daemon restart.
  - "Changes requested" is batched and **pasted into the original worker's session** as an "[AO reviewer] …" message carrying the head SHA. It asks the worker to reply on the GitHub review and resolve the threads.
  - Deduplication is `sendOnce` keyed on (PR, batch, signature), with **at most 3 nudges** per key (`reviewMaxNudge = 3`). If the worker has exited or is waiting for input, the review is *not* marked delivered and fires again later.
  - `RequestRereview` starts the next round. CI failures and merge conflicts go through the same reducer.
- **State.** SQLite locally (`storage/sqlite/migrations`, e.g. `0048_review_agent_session_id.sql`); Postgres in the cloud variant.
- **The board is derived.** Its kanban columns — Working, Needs you, In review, Ready to merge — are computed from facts (session, PR, CI, review), never set by an agent.

## Vibe Kanban: task attempts, and follow-ups by resume

Sources: `crates/executors/src/executors/claude.rs`, `actions/coding_agent_follow_up.rs`, `actions/review.rs` in [BloopAI/vibe-kanban](https://github.com/BloopAI/vibe-kanban).

- **Launch.** `claude -p --output-format=stream-json --input-format=stream-json --permission-prompt-tool=stdio`, so permission prompts reach the UI.
- **Follow-ups.** `--resume <session_id>`, and `--resume-session-at <msg uuid>` to cut the history short (a rewind).
- **Review.** A `ReviewRequest` takes its own `executor_config` (another vendor if wanted) and an *optional* `session_id`, so a review can start fresh or resume.
- **Human feedback.** Inline comments on the diff go to the same session as a follow-up.
- **State** is local SQLite. Nothing claims work autonomously: a person starts every attempt.
- **The sunset was commercial** ("vast majority are free users", [blog](https://www.vibekanban.com/blog/shutdown)), not technical.

## ccswarm and takt: declarative playbooks

Sources: [ccswarm](https://github.com/nwiizo/ccswarm) `crates/ccswarm/src/workflow/{flow,cycle,judge}.rs`; [takt](https://github.com/nrslib/takt).

- **Flows.** A flow is YAML: stages, each with `rules: [{condition, next}]`. The default is plan → "Sangha" quorum review → implement → review → fix.
- **Per stage:**
  - `provider: claude|codex` and `model`, which is how cross-vendor review is configured;
  - `permission: readonly`, which the README admits is **not enforced** on Codex;
  - `pass_previous_response`, default true. The source says to set it false "for fix stages where fresh context is preferred";
  - `output_contract`, `max_retries`, `timeout`, and `call:` for a sub-flow.
- **Routing** is by `[STEP:N]` tags in the output, an `ai("condition")` LLM judge, or `all()`/`any()` over parallel results.
- **Termination.** `max_stages` (default 30) and **`max_stage_visits` (default 3)**, which bounds a review→fix loop. Cycles are detected statically by `flow check`.
- **Launch.** `claude` with `--session-id`/`--continue`, `--max-budget-usd` and `--worktree`; or `codex exec` / `codex exec resume <thread>`. Runs are recorded under `.ccswarm/runs/<id>/`, and `ccswarm cost <run>` reports cost per stage.
- **Its own honest gap:** "Sangha … only compares the number of successful approvals with quorum; it does not resolve dissent or bind machine checks to the decision."
- **takt** is the older, more mature version of this YAML design ("movements" and "pieces").

## Shorter notes

- **Claude Code agent teams** ([docs](https://code.claude.com/docs/en/agent-teams)). Experimental and local.
  - A task list in `~/.claude/tasks/{team}/`, claimed with **file locks**, and JSON mailboxes in `~/.claude/teams/{team}/inboxes/{agent}.json`.
  - Teammates run in-process or in tmux/iTerm panes. They **do not run under `-p` or the SDK**.
  - The `TeammateIdle`, `TaskCreated` and `TaskCompleted` hooks can exit 2 to block and send feedback, which makes a cheap quality gate.
  - Known issues: task status lags, the lead stops early, and in-process teammates are not restored on resume.
- **Claude Squad.** `tmux new-session -d … <program>` on git worktrees. "Done" means the pane's content hash stopped changing or a prompt string showed (`session/tmux/tmux.go` `HasUpdated`). Its "daemon" presses Enter on prompts (AutoYes, `daemon/daemon.go`).
- **Agent Farm.** Types `cc` into 20+ Claude panes.
  - Coordination is *by prompt only*: an `active_work_registry.json` and `agent_locks/*.lock` files that agents are *asked* to respect.
  - It broadcasts `/clear` when context fills up, and detects readiness from the "Welcome to Claude Code!" banner.
- **ruflo / claude-flow.** An audit found about 10 of 300+ MCP tools real ("JSON state stubs"), and the "hive mind" is `spawn('claude', ['--dangerously-skip-permissions', …])` ([gist](https://gist.github.com/roman-rr/ed603b676af019b8740423d2bb8e4bf6), [issue #695](https://github.com/ruvnet/ruflo/issues/695)).
- **Spec Kit / Kiro.** Markdown planning artifacts in git (spec → plan → tasks → implement), with no orchestration at run time. DPlanner already has the "artifacts per phase in the repo" idea. Kiro (closed) adds event hooks on file save.
- **Sculptor.** A workspace per task, any terminal agent as the harness, and an experimental Docker/remote backend. People drive it.
- **Terragon.** A cloud sandbox per task running Claude or Codex CLIs. It shut down for lack of traction ([shutdown](https://docs.terragonlabs.com/docs/resources/shutdown)).
- **Conductor.** Closed source; the reference experience for a worktree per agent on one Mac ([overview](https://rywalker.com/research/conductor)).

## Side by side

| | Launch | Done when | Hand-back channel | Review feedback goes to | Claim | Stale claim | State | Rounds | Budget |
|---|---|---|---|---|---|---|---|---|---|
| Symphony | `codex app-server` on stdio (or SSH) | protocol turn event; stall/turn timeout | tracker tools; one workpad comment | same thread within a run; a new run reads the workpad | in memory, one orchestrator | reconciled each tick; the tracker is truth | tracker + workspace dir; `WORKFLOW.md` in repo | human-driven Rework; no cap | concurrency, turns, timeouts |
| Beads / Gas Town | tmux + send-keys; hooks | CLI verb `gt done` | beads (mail is beads) + tmux nudges | a fresh polecat, or a nudge | CAS in a transaction, re-read after | lease TTL, `heartbeat`, `reclaim`; replica-aware | Dolt, pushed to the git remote | self-review + parallel convoy; no cap | none ($100/h) |
| Paperclip | `claude --print stream-json --resume` per heartbeat | exit + parsed result | REST API, run JWT | **the original session (resumed)** | `checkout` + expectedStatuses → 409 | watchdog; never replays tools | Postgres | `in_review` + review policy | **monthly cents; 80% warn, 100% pause** |
| AO | native TUI in tmux, or chat; worktree | session activity + PR/CI facts | CLI verb `ao review submit` | **the original session (pasted)** | one worker per task | session guard | SQLite (Postgres in cloud) | ≤3 nudges per batch; cross-harness | — |
| Vibe Kanban | `claude -p` stream-json both ways | process exit | the UI | resume, optionally | a person starts it | — | SQLite | manual | — |
| ccswarm | `claude` / `codex exec` per stage | exit + tag or AI judge | stage output passed on; run dir | configurable: previous response or fresh | local queue | — | `.ccswarm/runs` files | **`max_stage_visits = 3`**, quorum | `--max-budget-usd` per call |
| CC agent teams | in-process or tmux panes | idle notification | JSON mailboxes, task files | the same teammate | file lock | none (it lags) | `~/.claude` | hooks exit 2 | — |

## Patterns worth taking

1. **A CLI verb is the only way back, idempotent and keyed by run.** `ao review submit --run --verdict`, `gt done`, Paperclip's run-id header. DPlanner's `status set` and `review post` are already this. What they lack is a `--run <id>` that makes a retry safe.
2. **Leases, not locks.** A claim is a compare-and-set naming the holder, run, host and expiry, renewed by a heartbeat. A reaper releases it after about 2× the TTL. A replica never reaps a lease another replica granted (Beads).
3. **Git-backed, but hot state not merged in git.** Beads moved claims and status onto a separate ref of the same remote. DPlanner's plan graph can stay git files while claims and heartbeats live elsewhere — a separate ref or a small server — so claim churn never conflicts with the plan.
4. **Reviewer feedback goes into the implementer's own session, and the reviewer is always fresh.** The original session gets a *structured delta*: verdict, head SHA, findings (Paperclip, AO). It falls back to a fresh session when the directory changed or the session is gone. The reviewer is a new session, often another vendor (AO `SwitchReviewer`, ccswarm `provider`, Yegge's "Fable review").
5. **The loop has an explicit bound.** A visit cap per stage (ccswarm 3, AO 3) and a cap on the whole flow, then a person.
6. **A round is keyed to the head SHA, and not "delivered" until the worker can actually receive it** (AO's `sendOnce` fires again).
7. **One persistent progress note per task** (Symphony's workpad) as memory across sessions — one evolving entry, not a log.
8. **The playbook is a versioned file in the repo** (Symphony `WORKFLOW.md`, ccswarm/takt YAML, Gas Town TOML), checked statically, with a dry run that renders the prompts.
9. **Reconcile before dispatch on every tick**, and detect a stall by time since the agent's last event (Symphony §8.5).
10. **The budget gate sits in the scheduler**: monthly caps with warn/pause (Paperclip) and per-call `--max-budget-usd` (ccswarm). A quota error is classified and waited out to its reset.
11. **The multiplayer board is derived from facts** (AO): holder, live run, PR/CI, verdict — and it shows holder, host and last heartbeat.
12. **Credentials stay in the orchestrator**; the agent sees tool results, not tokens (Symphony §11.5).

## Anti-patterns

- **Screen-scraping tmux** — pane hashes, banner text, prompt strings — and `send-keys` as an RPC. Gas Town calls its own "timing-sensitive". The non-interactive modes in [headless-mechanics.md](headless-mechanics.md) make it unnecessary.
- **An auto-yes daemon** that presses Enter (Claude Squad).
- **Coordination by prompt alone** (Agent Farm's lock files, ruflo's hive mind). A lock nobody enforces in code is a suggestion.
- **One serial supervisor in the completion path** (Gas Town's Witness, zombie polecats).
- **A zoo of role metaphors** — Mayor, Deacon, Witness, Refinery, Dogs. It is hard to reason about, and a runaway role deleted code. The meeting note's own warning applies: analogies trap your thinking.
- **No cost ceiling with N agents** (Gas Town at ~$100/h).
- **Agents allowed to commit to main or merge on red tests** (DoltHub's week).
- **Quorum by counting approvals**, with no machine check bound to the verdict, and a "readonly" reviewer that is not enforced (ccswarm on its own work).
- **A huge surface with weak trust boundaries** (Paperclip's CVSS 10). A playbook or config an agent supplied is untrusted input.
- **Experimental in-session teams as the basis for autonomy** (Claude Code agent teams: no `-p`, teammates lost on resume).
- **No convergence guard.** Yegge's "just two more things". A hard cap on rounds and a way out to a person are not optional.
