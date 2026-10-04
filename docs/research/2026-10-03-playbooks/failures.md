# Failures and edge cases: what goes wrong, and what happens next

*2026-10-03. Every case here is either simulated (`spike/simulate.py`, scenario named in brackets), or observed in the free probes (`spike/probes/`, which point each CLI at a fake API that fails on purpose — no real model call, no cost).*

## In short

**The rule everything follows:** the ledger is the truth, and processes are disposable. Every failure is classified into one of five classes:

| Class | Meaning | What the engine does | Spends a round? |
|---|---|---|---|
| **retry** | transient: crash, hang, 5xx, malformed output | back off 30 s → 2 min → 10 min; after 3 in a row → a person | never |
| **park** | quota or rate limit with a reset time | wait until the reset; tell the person; nothing else on that account launches | never |
| **person** | needs a human: login gone, billing, a question, a model that no longer exists | a typed interrupt in *Needs you*; other accounts' stages go on | never |
| **abandon** | will not get better by waiting: a runaway loop, a broken config | stop the run, then a person | never |
| **changes** | a real verdict from a gate | send back to the work stage | yes |

**What the probes found that we did not know:**
- **None of the three CLIs times out a hung API on its own.** In 5½ minutes, `claude -p`, `codex exec` and `opencode run` all sat silent. Only DPlanner's stall detector ends a hang.
- **`opencode` with a malformed 200 reply loops forever.** It sent 3,698 requests in 330 s and never exited. Worse, it **keeps emitting events**, so a stall detector based on "time since the last event" is blind to it. A second detector is needed: events with zero tokens, or the same step repeating.
- **Claude Code retries a 401 ten times over ~3 minutes** before saying "Invalid API key". A logged-out agent looks alive for three minutes. 429 and 500 retry for 3–4½ minutes too. **Codex gives up on a 429 at once** without honouring `retry-after`, and retries 401, 403 and 404 five times for nothing.
- **`opencode` with no login says only `UnknownError: Unexpected server error`.** Its error names nothing useful, so the classifier has to infer "probably auth" from context.
- **On SIGTERM, Claude exits 143; Codex and opencode die by the signal (-15).** None writes a final result event. A killed run is known by its exit, never by its output.
- **Codex with no config contacted the real `api.openai.com`** (no key was sent, and the 401 is free). A probe, or a worker, must pin its provider explicitly.

## The probe table

Each row is one run against `fake_api.py`. The class comes from `spike/classify.py`, which is checked against every fixture.

*(The full fixtures are in `spike/probes/out/*.json`; the report renders this table from them.)*

| Failure | claude | codex | opencode |
|---|---|---|---|
| not logged in | exit 1 in 0.4 s: "Not logged in · Please run /login" | exit 1 in 14.5 s, after 5 reconnects to the real API: "401 Unauthorized: Missing bearer" | exit 1 in 1.4 s: "UnknownError" (nothing useful) |
| 401 bad key | exit 1 after **179 s**, 10 retries: "Invalid API key" | exit 1 in 6.6 s, 5 retries | exit 1 in 1.9 s, `statusCode 401, isRetryable false` |
| 403 subscription lapsed | exit 1 in 1.0 s: "Failed to authenticate. API Error: 403" | exit 1 in 6.1 s, 5 retries | exit 1 in 1.9 s, `403` |
| credit too low | exit 1 in 0.9 s: "Credit balance is too low" | exit 1 in 0.1 s: "Quota exceeded. Check your plan and billing details." | exit 1 in 2.2 s, `400` + message |
| 429 rate limit | exit 1 after **262 s**, 10 retries | exit 1 in **0.1 s**: "exceeded retry limit, last status: 429" | exit 1 after 102 s, 9 requests, `isRetryable true` |
| 529 / 503 overloaded | exit 1 in 2.7 s: "Repeated 529 Overloaded errors" | exit 1 in 25 s, 30 requests | exit 1 after 69 s |
| 500 server error | exit 1 after 187 s, 10 retries | exit 1 in 25 s: "We're currently experiencing high demand" | exit 1 after 75 s |
| model retired (404) | exit 1 in 1.1 s: "There's an issue with the selected model" | exit 1 in 6.3 s, 5 retries | exit 1 in 2.1 s, `404` |
| malformed 200 | exit 1 in 1.0 s: "empty or malformed response" | exit 1 in 6.2 s: "stream disconnected before completion" | **never exits: 3,698 requests in 330 s, still emitting events** |
| API hangs | **no exit in 330 s**; only the `init` event | **no exit in 330 s**; `thread.started`, `turn.started` | **no exit in 330 s; no event at all** |
| SIGTERM | exit 143, no result event | killed (-15), no event | killed (-15) |
| SIGKILL | -9 | -9 | -9 |

**Consequences for the harness contract** (`domain/agents.py`):
- An `exec` template is not enough. A harness also needs:
  - a **`classify(exit, events, stderr)`** that maps its own error shapes to the five classes;
  - its **stall threshold**. opencode emits nothing before its first step finishes, so its threshold must cover a whole model call.
- The worker's runner adds a **runaway detector** on top of the stall detector: N events with no token progress, or a repeat rate above a bound.
- The **preflight** before every launch is a cheap auth check (`claude auth status`, `codex login status`). It turns the 3-minute dead-login retry storm into a 1-second `login` interrupt.

## Everything we could think of

Columns: how it is **detected**, its **class**, and **what happens**. Square brackets name the scenario in `simulate.py` that plays it.

### The agent process

| Case | Detected by | Class | What happens |
|---|---|---|---|
| Crashes (non-zero exit, OOM kill, segfault) | exit code, no verdict | retry | backoff, relaunch fresh; three in a row → person [`fail/crash`] |
| Hangs (no events) | time since the last stream event, monotonic clock, > the harness's stall threshold | retry | kill the process group, relaunch [`fail/hang`] |
| A long tool call that is not a hang (a 20-minute test run) | stream shows a tool *started* and not finished | — | the stall clock pauses while a tool runs, up to the stage's wall-clock limit |
| Overruns the wall clock | stage limit (work 45 min, review 20 min) | retry | kill, relaunch; three in a row → person: the step is probably too big [`fail/timeout`] |
| Loops: repeats steps, burns tokens | runaway detector: events without progress, repeated identical tool calls | abandon | kill, person; `--max-turns` / `--max-budget-usd` as the CLI's own cap |
| Exits 0 without a verdict | exit 0, no verdict in the ledger | — | resume it once with "give your verdict only" (a nudge, 5k tokens); still none → person [`fail/no-verdict`, `fail/no-verdict-twice`] |
| Malformed verdict | schema check on the final message (`--json-schema` / `--output-schema`) | retry | **never** read as changes; three in a row → person [`fail/garbled`] |
| Posts a verdict after it was killed | the verdict's run id ≠ the run holding the stage | refused | fencing: the late verdict is logged and ignored [`fail/late-verdict`] |
| Posts twice | idempotent verb keyed by run id | — | the second post is a no-op |
| Stops at a permission prompt | `--permission-prompts none` makes it a `permission_denied` event | person | "the reviewer needed X; allow it for this playbook?" |
| Asks a question | the agent's own `needs-input` state, or a verdict of kind *question* | person | *respond* in the inbox; the stage re-runs with the answer [`fail/question`] |
| Background subagents keep `-p` alive | process alive after the final result event | — | grace of 10 min (the CLI's own idle limit), then kill; the verdict already counts |

### The provider and the account

| Case | Detected by | Class | What happens |
|---|---|---|---|
| 5xx, overloaded | probe-observed messages (table above) | retry | the CLI already retried; DPlanner backs off on top |
| Rate limit (429) | as above | park | until `retry-after` or the provider's reset; never a round |
| Subscription usage window or weekly cap | the CLI's usage-limit message with its reset time | park | park the **account**, not the step: every stage on that account waits; tell the person; offer another profile only if it is at least as strong [`fail/quota`] |
| Programmatic credit exhausted (since 2026-06-15, secondary) | "credit balance too low" / "quota exceeded" | person | billing is a person's job; stages on other accounts go on |
| **Logged out / OAuth expired / subscription lapsed / payment failed** | 401/403 message; preflight auth check | person | **circuit breaker on the account**: no launch on it until a login is seen; a `login` interrupt; stages on other accounts continue [`fail/auth`] |
| …and the agent died mid-edit | the run ended in auth failure with a dirty worktree | — | after login: **resume** if the session survived (it is on disk), else **fresh** with "a previous run left these uncommitted changes" and the diff |
| Model retired or renamed | 404 "model" message | person | the playbook names a model the account cannot use: fix the role |
| CLI upgraded mid-playbook | harness version differs from the run's recorded version | — | warning; the prompt cache is invalid anyway (a version change resets it) |
| Context window exhausted / auto-compaction | the stream's compaction event; context over the warm limit | — | next run goes fresh with a written handoff instead of resuming |
| Prompt cache expired | time since the last event > TTL | — | not a failure: the fix runs fresh, and costs more [`careful/person-sends-back`] |

### The host and the orchestrator

| Case | Detected by | Class | What happens |
|---|---|---|---|
| Window closed / worker killed / reboot mid-stage | on start: a run record says live, but no process holds it | retry | **reconcile**: pid alive and stream growing → adopt; else mark lost and relaunch after backoff, never blind [`fail/lost-host`] |
| Laptop suspend: timers jump | monotonic clock jumps past the stall limit on wake | — | re-check liveness once on wake before killing anything |
| Two launchers (window + worker, two machines) | the shared lock file (one machine); leases + turn stamps (several) | — | the [coordination note](../2026-10-01-agent-orchestration/coordination.md); never two live runs on one step (the spike asserts it at every launch) |
| Plan-repo sync fails (pull or push rejected, ledger conflict) | git exit | retry | the ledger rows are append-only per run, so a merge never conflicts on the same row; a rejected push is retried after a pull |
| Disk full, run dir cleaned, worktree pruned | write errors; worktree missing on resume | person | resume is impossible → fresh with the ledger's findings; tell the person the worktree is gone |
| Clock skew between machines | — | — | turn stamps name the turn, not the time (as today); leases use the server's or ref's clock |

### The repository and the work

| Case | Detected by | Class | What happens |
|---|---|---|---|
| **Stale SHA**: someone pushed while the reviewer ran | verdict SHA ≠ head | refused | the verdict is ignored and the gate re-runs on the new head [`fail/stale`] |
| Implementer writes during review | (should not happen: one live run per step) | — | the reviewer works on a read-only snapshot at the SHA anyway |
| Base branch moved / merge conflict | the landing's own checks | — | the branch-landing stage, as today |
| **Flaky tests** | the failing test passes on one re-run inside the gate | — | pass, with the flake recorded on the step; never a round [`solo/flaky`] |
| Test environment missing | the command cannot start (exit 127, import error before collection) | retry → person | **an error, not changes**: the implementer cannot fix a missing toolchain [`fail/env-missing`] |
| Sandbox blocks the reviewer from running tests | permission-denied events | — | falls back to reading; the verdict says so |
| A "read-only" reviewer edits files | the worktree's diff changes during the review | refused | discard the edits; enforce with the sandbox, not the prompt (ccswarm's lesson) |
| **The implementer games the gate**: deletes/skips tests, edits protected paths | test count below base; skip markers added; protected-path globs | changes | the criteria gate says no, with the reason [`solo/gamed`] |
| The diff is too big for the reviewer's context | token estimate of the diff | person | split the step, or review per file group; never truncate silently |
| The diff is empty but the agent says done | `git diff --stat` empty | changes | sent back: "no changes were made" |

### The conversation

| Case | Detected by | Class | What happens |
|---|---|---|---|
| A and B never converge | the gate's rounds reach the cap | person | escalate with both positions [`review-loop/cap`] |
| **The goalposts move**: new findings every round (Yegge's "two more things") | findings in round n > 1 not linked to round n−1 | — | after round 1 the briefing says: verify the earlier findings, and raise only *high* severity new ones |
| Implementer declines a finding | a *decline* reply with a reason | — | recorded; if the gate insists at the cap, a person decides |
| The reviewer rubber-stamps | its approval rate vs. the person's send-back rate (statistics per playbook) | — | visible on the playbook page; no automatic action |
| Prompt injection in the repository tells the reviewer to approve | — | — | the reviewer never sees the implementer's justification; criteria gates are exit codes; a person gate on careful work |

### Specific to a lead agent

| Case | Detected by | Class | What happens |
|---|---|---|---|
| The lead dies | its process exits | retry | a fresh lead rebuilds from the ledger; children it started are reconciled like any orphan |
| **The lead says a gate passed when it did not** | a criteria verdict whose source is not DPlanner | refused | criteria are recorded by DPlanner from exit codes [`lead/lies-about-tests`] |
| The lead overruns budget or context | spend per launch; its own context size | person | the same budget gate as the engine |

### The person

| Case | Detected by | Class | What happens |
|---|---|---|---|
| A person gate is never answered | age of the open interrupt | — | a reminder after a day; it never times out into an approval |
| The step, its description or the playbook is edited mid-run | the run pins the playbook version and the description's hash | — | the run continues on what it started with; a notice says so; the next run uses the new text |
| A person takes over a running stage | *Take Over* | — | fence and stop the run, then hand the lease to the person ([floor.md](floor.md)) |
| Cancel | *Cancel Playbook* | — | kill, keep the worktree, offer cleaning |
| The step is deleted, relinked or moved mid-run | the model's change signal on the step | — | stop and keep the worktree; a deleted step's runs end as *abandoned* |
| Undo | — | — | a playbook's own status changes are external facts, off the undo stack (as auto-launch is today) |

### Budget

| Case | Detected by | Class | What happens |
|---|---|---|---|
| Spend reaches the ceiling | spend checked before each launch | person | a `budget` interrupt; criteria gates and a person's approval still go on — only spending launches are held [`fail/budget`] |
| The last run overshoots | — | — | a pre-launch check cannot stop a run halfway; the CLI's own cap (`--max-budget-usd <remaining>`) or a token kill must [`fail/budget` overshoots $1.20 by $0.13] |
| Usage only known at the end | — | — | stream usage events give a running count; the ledger is written at the end |
