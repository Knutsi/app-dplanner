# Tracking what each agent spends

*Research note, 2026-10-01. A snapshot: it records what we found that day and is not kept
current. Versions seen: Claude Code 2.1.280, Codex CLI 0.156.1, OpenCode 1.18.34.*

*Follow-up, 2026-10-01: the ledger and the tree readers proposed here were built — see
`domain/ledger.py`, `modules/step_agent_run/harvest.py` and ARCHITECTURE.md's *Usage is a
ledger, harvested by anyone*. Dollars were left out on purpose: tokens only.*

## The question

When a step in DPlanner is carried out by agents, we want to know:

1. **What each agent process spent**, including its subagents. Not "you used this much today",
   but "these three sessions, started from this plan, spent this much each".
2. **Which account paid.** A personal subscription, a company seat, or an API key.
3. **What that means in money or in quota.** Some accounts are billed per token (API, most
   Enterprise set-ups). Others are subscriptions with rolling limits (Claude Pro and Max,
   ChatGPT Plus and Pro), where a run costs no money but uses up part of a 5-hour and a weekly
   window.

And later:

- **Playbooks.** A step is run by several agents in a chain, for example an implementer and
  an adversarial reviewer from another vendor, until an **exit gate** passes. The step's cost is
  then the sum over all of them.
- **Headless runs**, which can be watched or joined from a terminal.
- **Estimates for a whole plan**, made from what similar steps cost before.

The three agent CLIs covered here are Claude Code, OpenAI Codex and OpenCode.

## The short answer

- **Exact per-session and per-subagent token counts can be read from all three CLIs**, from
  files they already write on this machine. No proxy and no API is needed.
- **DPlanner's current readers see only the main agent.** In the experiment below, today's
  Claude reader saw 42% of a small run's tokens and 18% of a large session's. The Codex reader
  missed a subagent that spent twice what its parent did.
- **Quota is account-wide in every vendor.** No CLI tells you what share of the 5-hour window
  one session used. It can only be estimated from a before/after reading, and that estimate
  becomes unreliable when two sessions overlap on one account.
- **Cost in dollars** is reported by Claude Code (at list price, even on a subscription), never
  by Codex locally, and by OpenCode from the models.dev price list (0 on subscription logins).
  So DPlanner needs its own versioned price table, and must label subscription figures as
  "API-equivalent", never as money spent.
- **Which account paid** can be read from each CLI's own status or auth file, without touching
  login tokens.
- The usage data should **not** live in the step's module data as it does now. See *Storage*
  below: a per-run, append-only ledger file is safe for many writers on many machines.

## What DPlanner does today

`modules/step_agent_run/usage.py` keeps one row per run on the step (`harness, session, input,
output, details, ended, prompt_chars`), keyed by session and recorded off the undo stack when
the shell ends. Each harness has a reader:

| Harness | Reader | What it misses |
|---|---|---|
| Claude | `agent_claude/harness.py` reads `<session>.jsonl`, one usage per message id | every subagent (they are separate files); output undercount inside a request (see traps) |
| Codex | `agent_codex/harness.py` finds the rollout by working directory and launch time, takes the last cumulative `token_count` | subagent threads (separate rollouts); the quota snapshot sitting in the same line |
| OpenCode | `agent_opencode/harness.py` takes the `session` row by directory and time | child sessions (`parent_id`) |

None of them record the model, the cost, the account or the quota. Codex and OpenCode are
found by "first session started in this directory after the launch", which can pick the wrong
session when two runs share a checkout.

## Claude Code

### Where the numbers are

**Transcripts.** `~/.claude/projects/<cwd with non-alphanumerics as ->/`:

```
<session-id>.jsonl                           the main agent
<session-id>/subagents/agent-<agentId>.jsonl one per subagent, nested ones flat beside them
<session-id>/subagents/agent-<agentId>.meta.json
    {"agentType":"Explore","description":…,"toolUseId":"toolu_…","spawnDepth":1,…}
```

Each `assistant` line carries the API's usage for that request:

```json
"message": {"id": "msg_…", "model": "claude-opus-5-5", "usage": {
  "input_tokens": 2, "cache_creation_input_tokens": 27380, "cache_read_input_tokens": 24649,
  "output_tokens": 646, "output_tokens_details": {"thinking_tokens": 22},
  "cache_creation": {"ephemeral_1h_input_tokens": 27380, "ephemeral_5m_input_tokens": 0},
  "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
  "service_tier": "standard", "inference_geo": "not_available", "speed": "standard"}}
```

Subagent lines carry `isSidechain: true`, their `agentId`, and the **parent's** `sessionId`.
The `meta.json` `toolUseId` matches the parent's Agent tool call. Transcripts are deleted after
`cleanupPeriodDays` (default 30), so they must be harvested before then.

**The `cost-state` line.** Undocumented, written into the main transcript when a session exits
normally (and restored on resume). It is Claude Code's own accounting, per model, and the same
number `/usage` and the status line show:

```json
{"type": "cost-state", "totalCostUSD": 0.0919, "modelUsage": {"claude-haiku-4-5-20251001": {
  "inputTokens": 77, "outputTokens": 4752, "thinkingTokens": 1609, "cacheReadInputTokens": 137431,
  "cacheCreationInputTokens": 37071, "webSearchRequests": 0, "costUSD": 0.0919}}}
```

It also counts small background calls (title generation and the like) that never reach a
transcript.

**Headless result.** `claude -p --output-format json` (or the last event of `stream-json`)
ends with `session_id`, `num_turns`, `total_cost_usd`, `usage` and `modelUsage` (per model,
with `costUSD` and `costBasis: "list"`). **`modelUsage` and `total_cost_usd` include
subagents. `usage` does not:** it is the last main-loop message only. Paperclip learned this
the hard way and its parser carries a comment saying so. Since 2.1.277 a resumed session
reports the whole session's total, so take the latest value and never sum across resumes.
`--max-budget-usd` caps a run.

**OpenTelemetry.** `CLAUDE_CODE_ENABLE_TELEMETRY=1` plus an OTLP endpoint. The metrics
`claude_code.token.usage` and `claude_code.cost.usage` and the event `claude_code.api_request`
carry `session.id`, `user.account_uuid`, `organization.id`, `user.email`, `model`, and
`query_source` (`main` / `subagent` / `auxiliary`). `OTEL_RESOURCE_ATTRIBUTES=
"dplanner.step_id=…,dplanner.run=…"` stamps every data point with our own ids. It is the
documented channel, but it needs a collector running.

**Hooks.** `SessionStart` (with `source`: startup, resume, clear, compact), `SessionEnd`,
`SubagentStop` (with `agent_transcript_path`). They carry `session_id` and `transcript_path`
but no usage. Note that **`/clear` starts a new session id**, so one step can span several
sessions.

**Status line.** Its JSON input has `session_id`, `cost.total_cost_usd`, the context window,
and, on Pro/Max, `rate_limits.five_hour` and `rate_limits.seven_day`, each with
`used_percentage` and `resets_at`. Interactive only.

**Process registry.** `~/.claude/sessions/<pid>.json` maps a pid to its `sessionId` and `cwd`.
Useful for an interactive terminal DPlanner spawned. Undocumented.

### Account and quota

- `claude auth status --json` gives `authMethod` (`claude.ai` or an API key), `apiProvider`
  (`firstParty`, Bedrock, Vertex…), `subscriptionType` (`max` here), `email`, `orgId`, `orgName`.
- `~/.claude.json` `.oauthAccount` adds `accountUuid`, `organizationUuid`, `organizationType`,
  `billingType` (`stripe_subscription`) and `organizationRateLimitTier`
  (`default_claude_max_5x`).
- Several accounts on one machine are several `CLAUDE_CONFIG_DIR`s, each with its own login and
  its own `projects/`. A run should record which one it used.
- Quota: the status line's `rate_limits`, or the undocumented `api.anthropic.com/api/oauth/usage`
  endpoint that tools like Paperclip call with the user's OAuth token. Anthropic's terms forbid
  third-party apps from collecting or using claude.ai credentials, so **DPlanner should not call
  that endpoint**. Running the unmodified `claude` binary under the user's own login is fine.
- Team and Enterprise plans with seats work like Max (5-hour and weekly windows). API-key and
  Console billing is per token, with daily per-user figures in the Claude Code Analytics API.

### Traps

- **One request, several lines.** A response is written as one line per content block, all
  sharing `message.id` and `requestId`. Dedupe on the pair.
- **Output tokens grow within a request** in subagent transcripts (issues #93620 and #98696):
  the first line of a request holds a placeholder and only the last holds the real count. Take
  the **maximum per field per request**. The experiment shows the first-line rule losing 99% of
  a subagent's output tokens.
- **Fork subagents** copy the parent's last record into their own file (#97978). Dedupe request
  ids across all files of a session.
- Skip lines whose model is `<synthetic>`.
- Strip `[1m]` from a model name before looking up a price.
- Price per request, not per session: subagents can run on other models.
- The cache-read price is not a uniform 0.1× of input. It is 0.05× on Opus 5.5 and 0.025× on
  Fable 5.1. One-hour cache writes cost 2×, five-minute writes 1.25×. US-only inference
  (`inference_geo: "us"`) costs 1.1×.

## Codex

### Where the numbers are

**Rollout files.** `~/.codex/sessions/YYYY/MM/DD/rollout-<local time>-<thread id>.jsonl`.
Relevant lines:

- `session_meta`: `id`, `session_id` (always the **root** thread's id), `cwd`, `source`
  (`cli`, `exec`, `vscode`, or `{"subagent": {"thread_spawn": {"parent_thread_id": …,
  "depth": 1, "agent_nickname": …}}}`), `parent_thread_id`, `thread_source`.
- `turn_context`: `model` and `effort`, enough to price the run.
- `event_msg` / `token_count`: cumulative `total_token_usage` and per-call
  `last_token_usage` (`input_tokens`, `cached_input_tokens` as a subset, `output_tokens`,
  `reasoning_output_tokens` as a subset, `total_tokens`), plus a **`rate_limits`** snapshot:

  ```json
  "rate_limits": {"primary": {"used_percent": 1.0, "window_minutes": 300, "resets_at": …},
                  "secondary": {"used_percent": 0.0, "window_minutes": 10080, "resets_at": …},
                  "credits": {"has_credits": false, …}, "plan_type": "plus"}
  ```
- **`token_usage_record`** (new; not in the docs yet): one line per model response with
  `thread_id`, root `session_id`, `root_turn_id`, `response_id`, and that response's `usage`.
  This is the cleanest per-request record of the three CLIs.

**The state database.** `~/.codex/state_5.sqlite` (open it read-only): table `threads` (`id`,
`rollout_path`, `source`, `cwd`, `model`, `tokens_used`, `agent_role`, …) and table
**`thread_spawn_edges(parent_thread_id, child_thread_id, status)`**, which is the subagent
tree.

**Headless.** `codex exec --json` emits `thread.started {thread_id}` and `turn.completed
{usage}`. The usage is the thread's cumulative total, and **for the main thread only**: the
source filters out subagent notifications. `--ephemeral` writes no rollout at all, so never use
it for a run that should be accounted.

**App server.** `codex app-server` is the JSON-RPC protocol behind the IDE extension. It
offers `thread/tokenUsage/updated` for every loaded thread including subagents, `account/read`
(`apiKey`, or `chatgpt` with `email` and `planType`), `account/rateLimits/read` and its update
notification, and `account/usage/read {threadId}` with an estimated dollar figure (probably
Business/Enterprise only). It is the richest way to host Codex headless.

**OpenTelemetry.** `[otel]` in `config.toml`. Events carry `conversation.id`,
`user.account_id`, `auth_mode` and token counts, and `codex.turn_cost` carries an estimated USD
figure when the backend supplies one.

**Hooks.** `SessionStart`, `SessionEnd`, `SubagentStart`, `SubagentStop`, `Stop`, each with
`session_id` and `transcript_path`. `CODEX_THREAD_ID` is exported to the agent's own
subprocesses. Project-level hooks run only once the user trusts them.

### Account and quota

- `~/.codex/auth.json` has `auth_mode` (`chatgpt` or API key) and an `id_token` whose claims
  include `chatgpt_plan_type`, `chatgpt_account_id` and `email`. Read the claims, never the
  tokens.
- Separate accounts are separate `CODEX_HOME`s.
- Plans have a 5-hour (`primary`) and a weekly (`secondary`) window, plus purchasable credits.
  The rollout's `used_percent` is account-wide and, as the experiment shows, coarse.

### Traps

- **No way to choose the session id up front.** Capture it from `thread.started`, a
  SessionStart hook, or the app server.
- A subagent's rollout starts with a **replay of its parent's history**. In the run below it
  carried two `session_meta` lines (its own first, then the parent's), and with the newer
  multi-agent mode it can also replay the parent's `token_count` lines. Count only from the
  child's own first `task_started`, or use `token_usage_record` filtered on `thread_id`.
- `turn.completed.usage` is cumulative, not a per-turn delta.
- No dollar cost anywhere locally on Plus/Pro. DPlanner prices it.

## OpenCode

- **Storage.** SQLite at `$OPENCODE_DB`, else `~/.local/share/opencode/opencode.db`. Older
  builds used JSON files under `storage/`, migrated on start. Table `session` has `parent_id`,
  `directory`, `title`, `metadata` (JSON), `agent`, `model`, and **rolled-up `cost`,
  `tokens_input`, `tokens_output`, `tokens_reasoning`, `tokens_cache_read`,
  `tokens_cache_write`** (schema checked on this machine). `step-finish` parts carry per-step
  `tokens` and `cost`.
- **Subagents.** The task tool creates a child session with `parent_id`. Its totals are **not**
  added to the parent, so roll them up recursively.
- **Headless.** `opencode run --format json` emits `step_finish` events with tokens and cost,
  but **for the main session only**. `opencode serve` (HTTP + SSE `/event`, JS SDK
  `@opencode-ai/sdk`) sees everything, including `GET /session/:id/children`.
- **Tagging.** No session id up front either, but `POST /session {title, metadata}` creates a
  session carrying our own metadata, and `opencode run --attach … --session <id>` runs in it. For
  the interactive TUI, a small plugin (`event` hook) can read a `DPLANNER_RUN` environment
  variable and record the session.
- **Cost** comes from models.dev prices. It is **0 for subscription logins** (the ChatGPT/Codex
  OAuth plugin zeroes it), so a 0 means "unknown", not "free".
- **Account.** `auth.json` is keyed by provider, with `type` `api` or `oauth`. No email, no
  quota.
- **Trap.** A message's `tokens` field is overwritten on every step (last step wins), while
  `cost` accumulates. Use the session columns or sum the step parts.

## The matrix

| | Claude Code | Codex | OpenCode |
|---|---|---|---|
| Per-session record | `<sid>.jsonl` + `<sid>/subagents/*.jsonl`; `cost-state` line | rollout files; `token_usage_record` per response; `state_5.sqlite` | `opencode.db` `session` row |
| Subagents | separate files in the session directory | separate threads, `thread_spawn_edges`, `session_id` = root | child sessions via `parent_id`, not rolled up |
| Choose the session id up front | yes, `--session-id` | no | no (create via `serve` with metadata) |
| Headless final event includes subagents | `modelUsage` and `total_cost_usd`: yes; `usage`: no | no (main thread only) | no (main session only) |
| Live protocol | `stream-json`, Agent SDK, ACP adapter | `app-server` JSON-RPC | `serve` + SSE, SDK, plugin |
| OpenTelemetry | yes, with custom resource attributes | yes | no |
| Dollar cost | estimated at list price, also on subscriptions | none locally | models.dev estimate; 0 on subscriptions |
| Which account | `claude auth status --json`, `.oauthAccount` | `auth.json` id-token claims | provider and auth type only |
| Subscription quota | status line `rate_limits` (5h, 7d) | `rate_limits` in every `token_count` line | none |
| Session-start hook | `SessionStart` | `SessionStart`, `SubagentStart` | plugin `event` |

## Experiment: what live runs showed

Run on 2026-10-01 with a throwaway probe script. Token columns: fresh input, cache write, cache
read, output.

### 1. This research session itself, read while running

The session that wrote this note (Opus 5.5), with three Explore subagents, read from its own
transcript files:

| Agent | Requests | Input | Cache write | Cache read | Output, first line | Output, max |
|---|---:|---:|---:|---:|---:|---:|
| main | 21 | 48 | 115,015 | 2,035,193 | 24,725 | 24,725 |
| Explore: Codex/OpenCode | 78 | 156 | 120,480 | 5,635,747 | 859 | 8,286 |
| Explore: Claude Code | 25 | 50 | 126,545 | 1,416,097 | 226 | 9,350 |
| Explore: orchestrators | 28 | 56 | 145,134 | 2,177,383 | 340 | 11,055 |
| **Tree** | | 310 | 507,174 | 11,264,420 | | **53,416** |

- **Today's DPlanner reader** would have recorded 2,174,981 tokens: **18%** of the tree's
  11,825,320, and 24,725 of 53,416 output tokens.
- **The first-line rule** loses 90–98% of each subagent's output tokens. The max rule is
  needed.
- **The "tokens" a finished subagent reports to its parent** (135,679 / 155,858 / 127,912 in
  the task notifications) are the size of its **last request**, not what it spent. The three
  subagents actually spent 1.55M, 2.33M and 5.76M tokens, nearly all cache reads. Never use
  that figure as cost.
- No `cost-state` line yet: it is written when the session exits.

### 2. A headless Claude run with one subagent

`claude -p --model haiku --session-id <uuid> --output-format json --max-budget-usd 0.50`, prompt
asking for one Explore subagent. Note: `--allowedTools` takes a list and swallows a positional
prompt, so the prompt went in on stdin. The run had to be started without this session's
`CLAUDECODE`/`CLAUDE_CODE_*` markers, or it would have run as a child session without a
transcript of its own (the markers DPlanner's Claude harness already scrubs).

| Source | Input | Cache write | Cache read | Output | Total | USD |
|---|---:|---:|---:|---:|---:|---:|
| result `usage` | 10 | 933 | 24,691 | 864 | 26,498 | |
| result `modelUsage` | 77 | 37,071 | 137,431 | 4,752 | 179,331 | 0.0919 |
| `cost-state` line | 77 | 37,071 | 137,431 | 4,752 | 179,331 | 0.0919 |
| transcripts, main + subagent, max rule | 77 | 37,071 | 137,431 | 4,752 | 179,331 | |
| transcripts, first-line rule | 77 | 37,071 | 137,431 | 1,223 | 175,802 | |
| today's DPlanner reader | 27 | 10,693 | 63,639 | 1,211 | 75,570 | |

- **The transcript tree read with the max rule matches Claude Code's own accounting to the
  token.** With no background calls on another model (the main agent was already Haiku), the
  three sources agree exactly.
- The result's `usage` is 15% of the real total. Use `modelUsage`.
- Today's reader records 42% of the tokens and 25% of the output.
- Account: `authMethod: "claude.ai"`, `subscriptionType: "max"`. The $0.09 is list-price
  equivalent: no money was spent, quota was.

### 3. A Codex run with one subagent

`codex exec --json -s read-only`, prompt asking it to spawn a subagent. Plan: ChatGPT Plus.

| Thread | Source | Total tokens | Cached input | Output |
|---|---|---:|---:|---:|
| parent `01a0f87c-9664…` | `exec` | 42,692 | 38,528 | 535 |
| child `01a0f87c-b183…` ("Herschel") | `subagent`, depth 1 | 88,641 | 63,616 | 953 |
| `exec --json` `turn.completed` | | 42,692 | 38,528 | 535 |

- **`exec --json` reported only the parent.** The subagent spent more than twice as much and
  was visible only in `thread_spawn_edges` and its own rollout. Today's DPlanner reader would
  also have recorded only 42,692 of 131,333 (33%).
- The `exec --json` stream did not show the spawn itself, only the `wait` call.
- The child's `token_count` totals started fresh (15,425 → 88,641): in this run no parent
  counts were replayed, but its first `session_meta` line was followed by the parent's.
- Quota: the 5-hour window went 0% → 1%, the weekly stayed 0%. For 131k tokens on Plus that is
  one whole step of a coarse integer gauge. **A per-run quota delta is visible only for large
  runs**, and only when nothing else ran on the account.

### 4. OpenCode

Not measured: no provider is logged in on this machine. The schema was checked read-only.

## Accounting: subscription versus API

Paperclip's split is the right one. Three separate axes for every run:

- **Provider**: whose model ran (Anthropic, OpenAI…).
- **Biller**: who charges for it (Anthropic, OpenAI, ChatGPT, OpenRouter, a company gateway…).
- **Billing kind**: `api` (metered per token), `subscription` (included in a plan, uses quota),
  `credits` (prepaid or overage), `unknown`.

Then:

- **Tokens are always exact and always recorded.** They are the unit estimates are made in.
- **Dollars on `api`** are real: price the tokens, or take the CLI's own figure where it
  gives one. Keep both to compare them.
- **Dollars on `subscription`** are an *API-equivalent*. They are worth showing ("this step
  would have cost $4.30 on the API"), because that is what a product owner can budget against,
  but never as spend.
- **Quota on `subscription`** is a before→after reading of the account's windows, flagged as
  shared when another run overlapped. It is the only honest per-run quota figure the vendors
  allow.
- **Which account** is the vendor's opaque account or organisation id plus a label the person
  chose. Not an email: the plan repository is shared.

## Storage: a ledger, not module data

### Why the current shape will not hold

Usage now lives in `steps/<step>/modules/agent_usage.json`: one read-modify-write JSON file
per step, inside the plan entries the store flushes. With a record per agent, playbook stages
running in parallel, and later daemons on several machines writing into the same plan
repository, that breaks three ways:

- **Collisions.** Two writers recording on one step race for one file. The store refuses one
  (`StaleWorkspaceError`); git conflicts on the same lines.
- **Noise.** Every recorded run is an outside change a window has to adopt.
- **Lost history.** Deleting or pasting a step drops what it cost, and estimating from history
  needs exactly that.

### The design

Usage is a **ledger of external facts**, not model state. Records are append-only and
immutable. Each has exactly one writer and a name no other writer can produce. Totals, cost
and estimates are derived on read.

```
<project>/
├── project.dproj
├── steps/
└── ledger/                       beside steps/, not one of the store's plan entries
    └── 2026-10/                  a month per folder keeps directories small
        └── <run ULID>.json       one file per run: one agent process tree
```

- **One file per run, named by a ULID** (time-ordered, unique across machines without
  coordination) minted at launch. Only the process that owns the run writes it, through
  `write_atomic`. It may write a provisional record at launch and replace it once at harvest. A
  provisional record whose run has gone stale is finalised by whoever harvests it next.
- **Safety from other writers is structural.** No file has two writers, so nothing needs a lock
  and no update is lost. Git sees only added files, so merges never conflict. This is the
  at-work claim's "one file per claim", applied to the plan repository.
- **Outside the store's plan entries.** Recording usage never makes a window adopt or settle
  anything and never trips `StaleWorkspaceError`. Windows read the ledger by their own poll.
  Save commits it with the project.
- **A record names its step by id and keeps a snapshot of it**: number, kind, the estimate at the
  time, playbook and stage. History survives the step being deleted, and estimates can group by
  these.

Record shape, format 1:

```json
{"format": 1, "run": "01J…", "project": "<id>", "step": "<id>",
 "step_snapshot": {"number": 7, "kind": "step", "estimate_days": 1.5},
 "playbook": "careful-change", "stage": "review", "role": "adversarial-reviewer",
 "harness": "claude", "harness_version": "2.1.280", "machine": "<host label>",
 "started": "…", "ended": "…", "outcome": "finished",
 "billing": {"provider": "anthropic", "biller": "anthropic", "kind": "subscription",
             "plan": "max", "account": "<opaque id>", "label": "Knut personal"},
 "agents": [
   {"id": "main", "parent": null, "session": "…", "agent_type": null, "models": {
      "claude-opus-5-5": {"input": 2, "cache_read": 24649, "cache_write_5m": 0,
                          "cache_write_1h": 27380, "output": 646, "reasoning": 22,
                          "web_search": 0}}},
   {"id": "a5a0…", "parent": "main", "agent_type": "Explore", "models": {}}],
 "reported_cost": {"usd": 4.31, "source": "claude cost-state"},
 "quota": {"5h": [12, 19], "7d": [40, 41], "shared": false},
 "sources": ["transcript", "cost-state"], "measurement": "native"}
```

- Tokens are kept **raw, per agent, per model and per token kind**, never pre-priced.
- Cost is derived through a **versioned price table** in `domain/`. A vendor-reported cost is
  kept beside it as a fact, so the two can be compared and old runs re-priced.
- `measurement` is `native`, `estimated`, `mixed` or `legacy`, so a surface can say how far to
  trust a number (an idea from ComposioHQ's Agent Orchestrator).

### Personal data stays off the plan

The record holds an opaque account id and a label. The label comes from a per-machine table,
`config_dir()/accounts.json`, mapping each id to a name the person chose ("Knut personal",
"Company Team seat"), with the plan type as the default. No email, and no login token is ever
read for anything but the plan and account claims.

### The per-machine side

- `config_dir()/usage/spool/<run ULID>.json`: what the launcher and a session-start hook or
  plugin learn while a run is live — session ids, transcript paths, pid, the quota reading at
  launch. A harvest turns it into the ledger record. This replaces matching by directory and
  launch time.
- `config_dir()/usage/index.sqlite`: an optional, disposable cache over all ledgers, only if
  reports or estimates get slow. Rebuilt from the JSON files, never the truth. SQLite is fine
  here because it never travels.

### Alternatives considered

- **One SQLite database in the plan repository**: git cannot merge it.
- **One JSONL file per step or per project**: two writers appending conflict on the last lines.
- **One JSONL file per writer** (machine or daemon): also conflict-free, but needs a writer
  identity scheme and rotation. File-per-run reuses what exists.
- **A server**: the multiplayer server in the v2 notes could take in these files unchanged when
  it comes.

**Migration.** Existing `agent_usage.json` rows become ledger records with `measurement:
"legacy"`, one main agent and an unknown model. The *Agent usage* aspect then reads the ledger.

## What orchestration projects do

| Project | How it tracks cost | Headless | Review / gate |
|---|---|---|---|
| **Paperclip** | parses each CLI's final event (Claude `modelUsage`, Codex `turn.completed`, OpenCode parts, ACP usage deltas) into an append-only `cost_events` ledger keyed by agent, issue, project and run; provider / biller / billing kind as separate fields; polls quota windows separately | yes: `claude -p` stream-json, `codex exec --json`, `opencode run`, ACP | per-issue execution policy: ordered review and approval stages, the executor may not review its own work, each decision recorded with a required comment; budgets warn at 80%, pause the agent at 100% |
| **Agent Orchestrator** (ComposioHQ) | tails Claude and Codex transcripts with byte cursors, own price table with a pricing version, `native_reported / estimated / mixed` | worktree per agent | CI failures and review comments routed back to the agent, with retry limits |
| **Gas Town** | a Stop hook reads the transcript into a cost journal, digested daily into git | tmux first | a merge queue with verification gates |
| **Vibe Kanban** | context-window fill only, not spend | headless stream-json, worktrees | human diff review |
| **Claude Code agent teams** | OTel and gateway headers carry agent and parent ids | **interactive only**: under `-p` teammates become plain subagents | `TaskCompleted` hook can refuse completion with feedback |
| **Ralph loop** | none | a Stop hook re-feeds the prompt until a completion phrase appears | the completion phrase is the gate; cap with max iterations |
| **BMAD Method** | none | prompt framework | adversarial review: three reviewers who must find issues, checked against acceptance criteria |
| **OpenHands SDK** | in-process metrics; delegates' metrics merged into the parent | SDK / server | agent-defined |
| Claude Squad, Conductor, Crystal/Nimbalyst, Sculptor, ccmanager | none found | tmux or app sessions over worktrees | human review |

Lessons for DPlanner:

1. Keep **one append-only ledger, separate from run logs**, and never rebuild billing from logs
   (Paperclip's rule).
2. Say where each number came from and how far to trust it.
3. Turn cumulative counters into per-run numbers by **subtracting a snapshot taken before**,
   never by summing.
4. Track **quota separately from money**, and treat "usage limit reached, resets at…" as a
   reason to wait, not a failure.
5. A **budget is a gate**: warn, then pause; pass `--max-budget-usd` to Claude per stage.
6. Agent teams cannot run headless, so a playbook must run its agents as separate processes and
   carry messages between them itself.

## Proxies, OpenTelemetry and ACP

- **A proxy** (LiteLLM, Helicone, Portkey) in front of the API sees every request. Claude Code
  even sends `x-claude-code-session-id`, `x-claude-code-agent-id` and
  `x-claude-code-parent-agent-id` to a gateway. With API keys that is exact attribution for every
  CLI at once. With a subscription login it is fragile (headers must be forwarded untouched,
  LiteLLM has an open bug billing the wrong account) and close to what Anthropic's terms forbid.
  Not a default; maybe an option for companies on API keys.
- **OpenTelemetry's GenAI conventions** (`gen_ai.usage.*`, `gen_ai.agent.id`) are still in
  development and have no cost attribute. Claude Code and Codex use their own names.
- **ACP** (the Agent Client Protocol from Zed) stabilised a session `usage_update` in June 2026:
  context size and an optional cumulative cost. Per-turn usage is still a draft, the Codex adapter
  sends no cost, and it says nothing about subagents or accounts. A possible uniform driver for
  headless runs later, not a source of accounting.

## How I would build it

1. **A usage record per agent, in a per-run ledger file** (above).
2. **Readers become tree readers.**
   - Claude: main plus `subagents/`, max rule, cross-checked against `cost-state` or the
     headless `modelUsage`.
   - Codex: root rollout plus children from `thread_spawn_edges`, using
     `token_usage_record` per thread.
   - OpenCode: the session and its `parent_id` descendants.
3. **Name the run at launch instead of guessing.** Claude already gets `--session-id`. Every
   harness gets `DPLANNER_RUN` and `DPLANNER_STEP` in its environment and a session-start hook
   (Claude, Codex) or plugin (OpenCode) writing `{run, session_id, transcript_path}` into the
   spool. Capture the account and a quota reading at launch and at harvest.
4. **A versioned price table in `domain/`**, used only on read.
5. **Playbooks.** Each stage is a run with a role. A step's cost is the sum over its runs. An
   exit gate is a stage whose verdict is recorded (decision plus comment), with a cap on rounds
   and on budget. This extends `step_review/rounds.py`.
6. **Headless hosts.** Claude: `-p --output-format stream-json`, joinable later with
   `claude --resume <id>` in a terminal. Codex: `app-server`, which also gives live usage,
   account and quota for every thread. OpenCode: `serve` with its event stream.
7. **Estimates.** Group past runs by playbook, role, harness and model, relate them to the
   step's estimate, and project over the plan: a derivation in the style of
   `domain/schedule.py`, handed a `cost_for(step)` function.

A first increment worth doing on its own: **fix the three readers to include subagents** and
record the model. It changes no format and the experiment shows it multiplies what we see by
two to five.

## Open questions

- Is a per-run quota delta worth recording when the gauge is this coarse (Codex moves in whole
  percents)?
- Should DPlanner run a local OpenTelemetry receiver, which would give per-request data and the
  account for Claude and Codex without reading private files?
- Where does the price table come from: a file shipped with DPlanner, or fetched (LiteLLM's or
  models.dev's list) with a pinned version?
- Do companies want the ledger in the plan repository at all, or in a separate repository or
  server they control?

## Sources

- Claude Code: [headless](https://code.claude.com/docs/en/headless),
  [cost tracking](https://code.claude.com/docs/en/agent-sdk/cost-tracking),
  [monitoring usage](https://code.claude.com/docs/en/monitoring-usage),
  [hooks](https://code.claude.com/docs/en/hooks),
  [status line](https://code.claude.com/docs/en/statusline),
  [authentication](https://code.claude.com/docs/en/authentication),
  [costs](https://code.claude.com/docs/en/costs),
  [LLM gateway](https://code.claude.com/docs/en/llm-gateway),
  [legal and compliance](https://code.claude.com/docs/en/legal-and-compliance),
  [pricing](https://platform.claude.com/docs/en/about-claude/pricing);
  issues [#93620](https://github.com/anthropics/claude-code/issues/93620),
  [#97978](https://github.com/anthropics/claude-code/issues/97978),
  [#98696](https://github.com/anthropics/claude-code/issues/98696),
  [#29721](https://github.com/anthropics/claude-code/issues/29721).
- Codex: [protocol.rs](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs),
  [exec events](https://github.com/openai/codex/blob/main/codex-rs/exec/src/exec_events.rs),
  [app-server protocol](https://github.com/openai/codex/tree/main/codex-rs/app-server-protocol/src/protocol/v2),
  [OTel events](https://github.com/openai/codex/blob/main/codex-rs/otel/src/events/session_telemetry.rs),
  [config](https://developers.openai.com/codex/config-advanced),
  [pricing](https://developers.openai.com/codex/pricing).
- OpenCode: [server](https://opencode.ai/docs/server/),
  [session](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/session.ts),
  [task tool](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/task.ts),
  [run](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/cli/cmd/run.ts).
- Tools and orchestrators: [ccusage](https://github.com/ryoppippi/ccusage),
  [Paperclip](https://github.com/paperclipai/paperclip) (cost ledger plan
  `doc/plans/2026-03-14-billing-ledger-and-reporting.md`, adapters under `packages/adapters/`),
  [Agent Orchestrator](https://github.com/ComposioHQ/agent-orchestrator),
  [Gas Town](https://github.com/gastownhall/gastown),
  [Vibe Kanban](https://github.com/BloopAI/vibe-kanban),
  [agent teams](https://code.claude.com/docs/en/agent-teams),
  [BMAD adversarial review](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/docs/explanation/adversarial-review.md),
  [OpenHands metrics](https://docs.openhands.dev/sdk/guides/metrics),
  [LiteLLM cost tracking](https://docs.litellm.ai/docs/proxy/cost_tracking).
- Standards: [OTel GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/),
  [ACP session usage](https://agentclientprotocol.com/rfds/session-usage).
- The experiment: transcripts and rollouts on the author's machine, 2026-10-01.
