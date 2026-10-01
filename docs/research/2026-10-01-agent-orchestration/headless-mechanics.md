# Running agent CLIs headless: flags, auth and the security baseline

*Gathered 2026-10-01. Two OpenAI pages (the harness-engineering post and "Unlocking the Codex harness") returned 403; anything about them comes from search summaries and secondary write-ups and is marked so. Other secondary claims are marked where they appear.*

Every DPlanner harness today (`modules/agent_claude/`, `agent_codex/`, `agent_opencode/`) opens an **interactive** session in a terminal. Claude's preset also starts in plan mode, waiting for a person. Each CLI below also has a non-interactive mode with structured output. That is what a worker needs, and it removes any reason to drive a terminal by hand (the tmux anti-pattern in [landscape.md](landscape.md)).

## Per CLI

### Claude Code

Docs: [headless](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference).

- **One task, then exit:** `claude -p "<prompt>"`, with exit 0 or non-zero.
- **`--bare`** skips CLAUDE.md, hooks, MCP, plugins and skills, so the run behaves the same on every machine. The docs recommend it for scripts and say it "will become the default for `-p`".
  - **Without `--bare`, `-p` runs a repository's `.claude/settings.json` hooks and `.mcp.json` servers in an untrusted folder with no trust dialog.** That matters for an unattended worker checking out branches an agent wrote.
  - The tension for DPlanner: our agents *want* the `dplanner` skill. Under `--bare`, the skill text goes in through `--append-system-prompt-file` or the briefing instead.
- **Output:**
  - `--output-format json` gives `result`, `session_id`, `usage`, `total_cost_usd` and a per-model cost breakdown. The cost is a client-side estimate, cumulative across `--resume`.
  - `--json-schema` returns a validated `structured_output`. This is how a reviewer's findings come back typed.
  - `stream-json --verbose` emits NDJSON events: `system/init` (which names MCP and plugin errors), `system/api_retry`, `permission_denied`, and a final `result`. Subagent messages carry `parent_tool_use_id`.
- **Sessions:** `--session-id` (we already pass one), `--resume <id | path to .jsonl>`, `--continue`.
- **Permissions:**
  - `--permission-mode auto | dontAsk | acceptEdits` and `--allowedTools "Bash(git diff *)"`.
  - `--permission-prompts none` (v2.1.259+) denies anything that would ask and tells the model not to retry.
- **Lifecycle:** SIGTERM exits 143 and runs SessionEnd hooks. A `-p` run stays alive while background subagents finish, up to 10 minutes idle by default.
- **Elsewhere:** the [Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) (Python/TS) is the same loop with a `canUseTool` callback. There is a [GitHub Action](https://code.claude.com/docs/en/github-actions), and `--cloud <session> -p` queues a message into a cloud session.
- **Agent teams do not spawn under `-p` or the SDK** ([agent teams](https://code.claude.com/docs/en/agent-teams)).

### OpenAI Codex CLI

Docs: [non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode), [CLI reference](https://developers.openai.com/codex/cli/reference).

- **`codex exec`** takes:
  - `--json`, which emits JSONL events: `thread.started`, `turn.started/completed/failed`, and `item.*` for messages, commands, file changes and MCP calls. Usage arrives on `turn.completed`.
  - `--output-schema <file>`, `-o/--output-last-message`, `--ephemeral`, `--skip-git-repo-check`.
  - `--sandbox read-only | workspace-write | danger-full-access`, defaulting to read-only. `--full-auto` is deprecated.
- **Resume:** `codex exec resume <SESSION_ID>`.
- **`codex review`** is a stable non-interactive review of uncommitted changes, a branch diff or a commit.
- **The App Server** is JSON-RPC 2.0 on stdio ([docs](https://developers.openai.com/codex/app-server)), with `thread/start`, `turn/start`, `thread/fork`, `turn/steer` and `turn/interrupt`. Threads persist and resume by id. Symphony drives it, one process per issue, reusing one `thread_id` for continuation turns ([SPEC](https://github.com/openai/symphony/blob/main/SPEC.md)). It replaces `codex mcp-server`, deprecated in v0.149.1 on 2026-08-24 ([secondary](https://codex.danielvaughan.com/2026/08/25/codex-mcp-server-deprecated-app-server-migration-claude-code-plugin-v0149/)).
- **Auth.** Use `CODEX_API_KEY`. OpenAI advises against `codex login` (ChatGPT login) in automation. API-key auth gets no cloud features, and Codex cloud needs a ChatGPT plan ([help](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)).
- **The Linux sandbox** is bubblewrap + Landlock + seccomp ([analysis](https://agent-safehouse.dev/docs/agent-investigations/codex)).

### The others

| CLI | Non-interactive | Structured output | Resume | Server auth | Notes |
|---|---|---|---|---|---|
| Gemini CLI ([headless](https://geminicli.com/docs/cli/headless/)) | `-p`, `--approval-mode yolo` | `json` / `stream-json` (`stats` carries tokens) | `-r latest` | `GEMINI_API_KEY` | Exit codes: 0 ok, 1 error, 42 bad input, 53 turn limit. Speaks ACP with `--acp`. |
| Cursor CLI ([headless](https://cursor.com/docs/cli/headless)) | `cursor-agent -p --force` | `json` / `stream-json` | — | `CURSOR_API_KEY` | Without `--force` it only *proposes* changes. |
| OpenCode ([server](https://opencode.ai/docs/server/), [CLI](https://opencode.ai/docs/cli/)) | `opencode run`, `opencode serve` (HTTP + OpenAPI) | `--format json` (NDJSON) | `run --attach http://host:4096`, sessions over HTTP | provider keys | A long-lived server that holds sessions; a good fit for a daemon. |
| Amp ([`-x`](https://ampcode.com/news/amp-x), [stream JSON](https://ampcode.com/news/streaming-json)) | `amp -x` | `--stream-json`, `--stream-json-input` | — | `AMP_API_KEY` | Claude-Code-compatible JSONL per one wrapper ([pkg.go.dev](https://pkg.go.dev/github.com/RenseiAI/donmai/provider/amp)). |
| Aider ([scripting](https://aider.chat/docs/scripting.html)) | `--message[-file] --yes-always` | none | none | provider keys | `--auto-test --test-cmd`; an unofficial Python API. |
| Factory ([droid exec](https://docs.factory.ai/guides/building/droid-exec-tutorial)) | `droid exec` | yes | — | API key | Closed. |

**What this means for a DPlanner harness:** the `AgentHarness` contract (`domain/agents.py`) has `command`, `open_command` and `resume`. It wants one more template, an **`exec`** command, for a run that takes the briefing, runs to the end without a terminal and prints a result DPlanner can parse. Its result is normalised into the same `RunReport(session, Usage)` the `report()` function already returns from the CLI's files. With stream-json it can come from stdout instead, which also gives a liveness signal (time since the last event) for stall detection.

## Auth, and what a subscription may do

- **Claude.** [Legal & compliance](https://code.claude.com/docs/en/legal-and-compliance) says OAuth (subscription) login is for "ordinary use of Claude Code". Developers building products, "including those using the Agent SDK, should use API key authentication." No third party may route requests through Free/Pro/Max credentials, and Pro/Max limits "assume ordinary, individual usage of Claude Code and the Agent SDK."
- **The June credit (secondary).** From 2026-06-15, programmatic use (Agent SDK, `claude -p`, GitHub Actions) draws on a separate monthly credit billed at API rates: $20 on Pro, $100 on Max 5x, $200 on Max 20x ([InfoWorld](https://www.infoworld.com/article/4171274/anthropic-puts-claude-agents-on-a-meter-across-its-subscriptions.html)). Check the current terms before relying on the figures.
- **OpenAI** advises API keys for automation and ChatGPT login for a person's own use.

So: **a worker on the developer's own machine, running the developer's unmodified CLI, on their own plan, is the "ordinary use" case. A worker on a server is a product, and runs on API keys.** The worker should make its auth source an explicit setting, not something it inherits from whatever the shell has.

## The security baseline for an unattended agent

The main risk is **prompt injection with nobody watching**.

- **Willison's "lethal trifecta":** private data, untrusted content and a way to communicate out ([post](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)).
- **Meta's "Agents Rule of Two" (2025-10-31):** an agent holding all three needs supervision ([Meta](https://ai.meta.com/blog/practical-ai-agent-security/)).
- **These have happened.** "Comment and Control" / PromptPwnd: text in an issue made Actions agents exfiltrate `GITHUB_TOKEN` and API keys ([CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-ai-coding-agent-ci-prompt-injection-202608/), [Aikido](https://www.aikido.dev/blog/promptpwnd-github-actions-ai-agents)). The Cline supply-chain compromise, 2026-02-17 ([CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-ai-github-actions-security-20260503-csa-st/)).

What a DPlanner worker should do, in order of cost:

1. **Run `--bare` (or its equivalent)**, so a branch an agent wrote cannot add hooks or MCP servers the next agent runs.
2. **Sandbox the agent.** Claude Code's sandbox ([docs](https://code.claude.com/docs/en/sandboxing)) uses bubblewrap + socat on Linux and Seatbelt on macOS, with network through a domain-allowlist proxy. `allowUnsandboxedCommands: false` removes the escape hatch. `sandbox.credentials` can **mask** a secret: commands see a placeholder, and the proxy injects the real token only toward allowed `injectHosts`. Codex's `workspace-write` sandbox does the same job. On a server, add a container per run.
3. **Keep the push credential out of the agent.** Either the worker pushes after the run, or a masked credential handles it. Use [GitHub App installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app): one hour, one repository. Push only to `agent/*` branches, with main protected. An agent never merges — already DPlanner's rule.
4. **Strip secrets from subprocesses** (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`).
5. **Treat issue, PR and spec text as untrusted.** A stage that needs the web, secrets *and* a push is a stage a person approves.
6. **Give review stages read-only permissions, enforced by the sandbox, not asked for in the prompt** — ccswarm's "readonly" that Codex ignored is the warning. DPlanner's review already "commits nothing" by briefing. Headless, that becomes `--sandbox read-only` / a deny on Write and Edit.
