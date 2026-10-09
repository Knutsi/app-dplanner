# Headless agents: questions, plan approval, limits and never getting stuck

*2026-10-07. A reality check run before planning "Playbooks and autonomous work". Every
claim below was observed in this session on Claude Code 2.1.280, Codex CLI 0.160.0 and
opencode 1.18.34, in a throwaway git repo in the scratchpad, unless it is marked as coming
from earlier notes. It builds on the [playbooks](../2026-10-03-playbooks/README.md) research
(shape, failure classes, free fake-API probes) and on the
[autonomous run](../2026-10-04-autonomous-run/README.md) (what a director had to do by hand).*

**Read [report.html](report.html) for the summary with the evidence laid out.**

## The question

Can DPlanner run Claude Code, Codex and opencode headless for every stage of a playbook, with:
- plan mode and its approval;
- the agents' questions lifted into DPlanner and answered there;
- no headless agent ever stuck;
- a hold when tokens run out, with a manual retry;
- a check that each agent is installed *and usable* on this machine?

## Summary

**Yes, if DPlanner never waits on a process.** The design that every experiment supports
is **park and resume**:
- A headless run is one turn of a process that then exits.
- A question or a plan approval is *recorded* and the process ends.
- The answer *resumes the same session*:
  - `claude -p --resume <id>`
  - `codex exec resume <id>`
  - `opencode run -s <id>`
- Because nothing holds a process open for a person, a closed window, a reboot or an
  exhausted quota costs time and nothing else.

**What the experiments showed:**

1. **Headless Claude cannot ask its native question at all.**
   - `-p` removes `AskUserQuestion`, even when `--tools` names it, and disables `ExitPlanMode`.
   - The agent asks in prose instead, and the run ends `success`, exit 0.
   - So a headless "success" can hide an open question. DPlanner has to classify how a run
     *ended*, not just whether it exited.
2. **One question door works for all three CLIs: a CLI command the briefing names.**
   - Each agent was told to run `ask "<question>" --choice A --choice B`. Claude (Haiku),
     Codex and opencode (`big-pickle`) all ran it, then stopped without touching the code.
   - Each finished the task when its session was resumed with the answer.
   - Claude and Codex took under 10 s per side, opencode about 18 s.
3. **Claude as an SDK host gives structured questions.**
   - Driven over `--input-format stream-json` with `--permission-prompt-tool stdio`, Claude
     *does* offer `AskUserQuestion` and `ExitPlanMode`.
   - Each arrives as a `can_use_tool` control request carrying the question, a header and
     options with descriptions. That is exactly a Control Centre card.
   - The host answers through `updatedInput.answers`, and the agent carried on.
   - This needs a live process, so it is the *warm* path, not the durable one.
4. **Plan mode works headless as plan → park → resume to execute.**
   - `claude -p --permission-mode plan` returns the plan as its final text.
   - `--resume <id> --permission-mode acceptEdits "Plan approved…"` implemented it.
   - Codex has no plan mode in `exec`. Its equivalent is a `-s read-only` stage that answers
     with the plan or diff, then `exec resume` in `workspace-write`.
5. **None of the three blocks headless on a permission. Each fails quietly instead.**
   - Claude records `permission_denials` in the result and still says `success`. Its final
     text was "Waiting for approval to run the verification test".
   - Codex in `read-only` explains, and returns the change as text.
   - opencode prints `permission requested: edit (calc.py); auto-rejecting` to stderr. It
     exits 0 with nothing done and no final text.
   - A supervisor must read these as *person* or *retry* endings, never as done.
6. **`claude --bg` is not headless.**
   - It is an interactive session in the background. It created its own worktree, then sat
     at "This command requires approval" indefinitely.
   - It is attachable (`claude attach`), and so is the right tool for a *person* to watch.
     It is the wrong tool for unattended work.
7. **Unattended execution needs an auto-approving mode per harness.**
   - Claude `--permission-mode auto` worked on Sonnet: it edited, ran the check and
     committed. On Haiku it denied the edit.
   - Codex `--approve-for-me` did the same on its default model.
   - `acceptEdits` alone denies every Bash call.
8. **Limits can be held proactively and resumed afterwards.**
   - Claude's `stream-json` emits a `rate_limit_event` on every run, with `utilization` and
     `resetsAt` for the five-hour and seven-day windows.
   - Codex's rollout file has `rate_limits.primary/secondary.{used_percent, resets_at}` and
     `rate_limit_reached_type`. The `--json` stream carries none of it.
   - On a forced subscription-style 429, Claude exited in 1 s. The result was
     `is_error: true`, `api_error_status: 429` and an assistant `error: "rate_limit"`.
     **The session file had already been written**, so the session can be resumed after the reset.
   - The 10-04 run's Codex log has the real event: `codex_error_info: "usage_limit_exceeded"`,
     "…try again at Oct 5th, 2026 2:22 AM". That *same* session was resumed after the reset
     and finished its review.
9. **Installed is not usable.**

   | Agent | Check | Result here |
   |---|---|---|
   | Claude Code | `claude auth status` | JSON, `loggedIn: true` |
   | Codex | `codex login status` | "Logged in using ChatGPT" |
   | opencode | `opencode auth list` | 0 credentials |
   | cursor-agent | `cursor-agent status` | "Not logged in" |

   - opencode still ran: its built-in `opencode/*` models need no login. So its check is
     "has a provider or a free model", not "has credentials".
   - A status check has three levels: on PATH, version, signed in.
10. **Headless Claude inherits the user's claude.ai connectors.**
    - Gmail send, Calendar and Docs appeared in a step agent's tools.
    - A step agent should run with `--strict-mcp-config` and DPlanner's own MCP list.
11. **Claude's plan mode writes the plan to `~/.claude/plans/`, even headless.**
    - Plan files from unattended runs pile up in the user's global directory.
    - The run directory, not that folder, should hold DPlanner's copy of the plan.

## Consequences for the design

**The question door.**
- `dplanner ask <question> [--choice …] [--kind decision|approval|blocked]` records a
  question on the run and tells the agent to end its turn. It works for every harness,
  because every harness can run a shell command.
- Native asks are adapters into the same record:
  - Claude's `AskUserQuestion` and `ExitPlanMode`, when DPlanner hosts the process (warm).
  - Claude's plan text, when a plan stage ends.
  - Permission denials.
  - herdr's `blocked` state for terminal runs. Those questions are answered in the terminal,
    but they are shown in the inbox.

**How a run ended**, classified per harness from the stream and the result:

| Class | Read from |
|---|---|
| done | — |
| asked | a question record, or prose ending in a question with no record |
| denied | `permission_denials`, an opencode auto-reject, Codex read-only |
| limit | `rate_limit`, `usage_limit_exceeded` |
| failed | the earlier probe classes |

- `--json-schema` (Claude) and `--output-schema` (Codex) can make the final message a
  typed `{outcome, summary, question?}`, so the classifier does not guess from prose.

**Parking and resuming.**
- A parked run keeps its session id.
- Answering, the limit reset or **Retry now** resumes it with one prompt: the answer,
  "continue", or "your limit reset, continue".
- A run never sits in a terminal for a person.

**The execute stage.**
- Claude: `-p --permission-mode auto`, on a model that supports it, or `acceptEdits` plus an
  allow-list.
- Codex: `exec --approve-for-me`, with the plan repo as `--add-dir`. The 10-04 run hit 21
  sandbox prompts because that repo was outside the writable roots.
  - *Correction, 2026-10-07 (S8):* that holds for a fresh `exec` only. `codex exec resume`
    (0.160.0) accepts none of `-s`, `--approve-for-me` or `--add-dir`, and a resumed thread
    does not keep its mode, so a resume — and, for one spelling, every turn — states it as
    `-c` overrides: `sandbox_mode="workspace-write"`, `approval_policy="on-request"`,
    `approvals_reviewer="auto_review"`, `sandbox_workspace_write.writable_roots=[…]`
    (checked on the rollout's `turn_context` against the fake API).
    `docs/architecture/playbooks.md` has the table as built.
- opencode: `run --auto`, or a permission config.

**Before every launch.**
- The account's last-known limit (Claude `rate_limit_event`, Codex rollout `rate_limits`)
  holds new launches above a threshold, until `resetsAt`.
- The auth preflight (the table above) turns a dead login into a one-second *person* ending
  instead of Claude's three-minute retry storm.

## What was not tested

- A real subscription limit on Claude. The 429 was a fake API with the unified rate-limit
  headers, so the exact wording of the real message is unseen. `rate_limit_event`'s
  `resetsAt` is real.
- Codex's `app-server` JSON-RPC approval flow, which is the warm path for Codex.
- Claude hooks (`PreToolUse` on `AskUserQuestion`) in an interactive terminal run, the way
  to mirror a terminal question into the inbox.
- Long runs: stall detection on real work, compaction, and resuming after hours. The
  earlier probes cover hangs.

## Evidence

- [evidence/run.sh](evidence/run.sh): runs one CLI on a fresh copy of the toy repo and
  records stdout, stderr, the exit code and the duration.
- [evidence/host.py](evidence/host.py): a minimal SDK host that answers `can_use_tool`
  (experiment E4).
- [evidence/ask_stub.sh](evidence/ask_stub.sh): the stub `dplanner ask` (E5, E7).
- [evidence/fake_api_usage_mode.diff](evidence/fake_api_usage_mode.diff): a `usage` mode
  for the earlier probe's fake API, a 429 with unified rate-limit headers and
  `x-should-retry: false` (E8).

Raw outputs were kept out of the repository, because they include the account's identity
and the session list.
