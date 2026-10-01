# Hand-back and review: what it costs, and what the evidence says

*Gathered 2026-10-01. Secondary sources are marked.*

A playbook is mostly hand-backs: a reviewer finds something, and somebody fixes it. There are two ways to send a finding back:

- **Resume the implementer's own session** with the findings appended. It remembers why it did what it did.
- **Start a fresh agent** with a written handoff: the findings, the diff and the step's briefing. It starts clean, and pays to re-read the files.

Which is cheaper and which is better depends on prompt caching and on context rot.

## Prompt caching decides the price of resuming

**Anthropic's prices** ([prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)):

| | Price, relative to plain input |
|---|---|
| Write, 5-minute TTL | 1.25× |
| Write, 1-hour TTL | 2× |
| Read | 0.1× (0.05× on Opus 5.5: $0.20 vs $4 per MTok) |

Each hit refreshes the TTL. The prefix (tools → system → messages) must match exactly. Caches are per workspace or organisation and never shared across organisations.

**OpenAI** caches automatically. On gpt-5.5 and later, 24-hour retention is reported as the default ([guide](https://platform.openai.com/docs/guides/prompt-caching); the 24 h detail comes from search summaries).

**Claude Code** ([prompt caching in Claude Code](https://code.claude.com/docs/en/prompt-caching)):

- The main conversation, `-p` and SDK turns included, gets a **1-hour TTL only on a subscription within its plan's usage**. On an API key it is **5 minutes** unless `CLAUDE_CODE_PROMPT_CACHE_TTL=1h` (or `promptCacheTtl`) is set. Subagents default to 5 minutes (`subagentPromptCacheTtl`).
- `--resume` resends the whole conversation, and hits the cache for "whatever part of its prefix is unchanged and still within the cache lifetime". It keeps the original system prompt.
- The cache is invalidated by changing the model, changing effort on most models, connecting MCP servers when tool search is off, and upgrading Claude Code.
- The cwd and git snapshot are in the prefix, so a cache is in practice **one machine and one directory**.
- `--output-format json` reports `ephemeral_1h_input_tokens` and `ephemeral_5m_input_tokens`, so a worker can see which it got.

**The arithmetic.** Take an implementer with a 150k-token context.

- **Resumed warm**, it re-reads 150k at 0.1×, the cost of about 15k fresh tokens.
- **Resumed cold** — say the review took 20 minutes against a 5-minute TTL — it re-reads all 150k at full price, plus a new cache write.
- **A fresh fixer** with a 10k-token handoff and 40k of file reads costs about 50k.

So: **warm resume < fresh handoff < cold resume.** The deciding fact is whether the review finished inside the TTL. A worker knows that, because it knows when the implementer's last request was made.

## Context rot argues against resuming forever

- **Every model degrades as input grows.** Chroma tested 18 models and all of them did ([Context Rot, Jul 2025](https://www.trychroma.com/research/context-rot)).
- **Compaction is no cure.** It replaces the history and rebuilds the cache, and compacting a cold session is expensive ([costs](https://code.claude.com/docs/en/costs)).
- **Anthropic's long-running harness post (2025-11-26) found compaction "insufficient"** ([post](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)). What worked was an initializer agent followed by **fresh coding sessions**. They hand off through a `claude-progress.txt`, a JSON feature list and git commits. That is a written handoff, and it is the shape DPlanner's briefing already has: the step's description, the notes, the *Review rounds* section.

## Does more agents help?

The token multipliers:

- An agent uses about **4×** the tokens of a chat, and a multi-agent system about **15×**. On research, multi-agent beat single-agent by 90.2%, and token usage alone explained 80% of the variance in performance. But "coding involve[s] fewer truly parallelizable tasks" ([Anthropic, multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)).
- Claude Code agent teams use about **7×** a standard session's tokens in plan mode. The enterprise average is about **$13 per developer per active day** ([costs](https://code.claude.com/docs/en/costs)).

Where it helps:

- **Cognition, "Don't Build Multi-Agents" (2025-06-12):** share the full trace, because every action carries implicit decisions ([post](https://cognition.com/blog/dont-build-multi-agents)).
- **The same company, "Multi-Agents: What's Actually Working" (2026-04-22):** it works when **"writes stay single-threaded"** and the other agents contribute judgement, not edits. A reviewer does better with **fresh context**. Devin Review averages 2 bugs per PR, 58% of them severe. A "smart friend" consult across frontier models works ([post](https://cognition.com/blog/multi-agents-working)).
- **OpenAI's harness engineering (2026-02-11):** about 1M lines written by agents, with agent-to-agent PR review ([summary](https://businessdatasolutions.github.io/ai-wiki/sources/2026-02-11-lopopolo-codex-harness-engineering); secondary — the original returned 403).
- **Amp's Oracle:** a second opinion from another vendor's model, *on demand*, not an always-on debate ([Amp](https://ampcode.com/news/gpt-5.4-the-new-oracle)).

**What this says for a playbook:** one writer per step, with reviewers that read and judge. That is DPlanner's model already — a review "commits nothing". A playbook is roughly 1 implementer + N reviewer passes. Each reviewer pass is a fresh read of the diff and its context, so its cost scales with the diff, not with the implementer's history.

## Does a reviewer from another vendor catch more?

- **Self-preference is real.** An LLM judge recognises and favours its own outputs (Panickssery, Bowman & Feng, [NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/7f1f0218e45f5414c79c0679633e47bc-Paper-Conference.pdf); [arXiv 2410.21819](https://arxiv.org/html/2410.21819v1)).
- **Greptile (2026-07-21), 2 × 500 PRs, recall on high-severity bugs:** each model "finds more bugs in the other model's code" ([blog](https://www.greptile.com/blog/model-inversion)).

  | Reviewer | Claude-written code | Codex-written code |
  |---|---|---|
  | Claude | 53.7% | 62.0% |
  | GPT | 50.5% | 60.0% |

- **[arXiv 2607.21656](https://arxiv.org/html/2607.21656v1) (Jul 2026), 116 LiveCodeBench tasks:**
  - Claude Opus 4.7 reviewing Codex's work raised the pass rate from 71.6% to 89.7% (+18.1 pp), against +12.9 pp for Codex reviewing itself.
  - **Codex reviewing Claude's work made it worse**: 91.4% → 82.8%, 13 regressions for 3 fixes.
  - Cross-model review cost about $0.25 per task.

**The rule this gives:** a reviewer from another vendor helps **when it is at least as strong as the author**, and can hurt when it is weaker. A reviewer's suggestions are advisory. A fix is gated by the tests, not by the reviewer's say-so.

**The products** (for scale):
- **Claude Code Review (2026-03-09):** parallel agents plus a verification pass. PRs with substantive comments went from 16% to 54%, with under 1% of findings marked incorrect. It costs **$15–25 and about 20 minutes per PR** ([blog](https://claude.com/blog/code-review)).
- **Cursor Bugbot:** 78% of findings resolved by merge, using learned rules ([blog](https://cursor.com/blog/bugbot-learning)).
- **The Codex plugin for Claude Code** adds `/codex:review` and `/codex:adversarial-review` ([repo](https://github.com/openai/codex-plugin-cc)), the cross-vendor pairing as a slash command.

## How many rounds?

- Self-Refine's gains shrink with every iteration ([arXiv 2303.17651](https://arxiv.org/pdf/2303.17651)).
- In self-repair, **two rounds capture 76–95% of the gain**, and the first round gives the most ([arXiv 2604.10508](https://arxiv.org/html/2604.10508)).
- Another study saturates at about three loops ([arXiv 2507.05598](https://arxiv.org/pdf/2507.05598)).
- In practice, the orchestrators that bound the loop at all cap it at three (ccswarm `max_stage_visits`, AO `reviewMaxNudge`). The ones that do not have the convergence failure: Yegge's "just two more things" ([essay](https://yegge.ai/essays/the-shape-of-things-to-come/)).

**Two review→fix rounds by default, then a person**, is the evidence-backed cap. `step_review`'s cap is three today, absent meaning the default. A playbook stage can set two.

## Per step, or per branch?

A review has a large fixed cost: reading the diff and enough of the codebase to judge it. Claude Code Review's $15–25 per PR is mostly that.

- **Reviewing five parallel steps one by one** pays that fixed cost five times, and never sees how the five fit together.
- **Reviewing the branch they land on** pays it once and sees the integration. Against that, recall falls as a diff grows, and a finding is further from the agent that wrote the code.

The split that follows:

- **Light, cheap gates per step:** tests, lint, a self-check by the implementer, at most one same-vendor pass.
- **The expensive, adversarial, cross-vendor stages once, on the branch** before its PR to main. Those stages may make fixes themselves on the branch, since the per-step agents are gone by then.

This is the pairing [proposal.md](proposal.md) recommends.

## The hand-back policy that falls out

1. **Reviewers always start fresh**, from another vendor at least as strong as the implementer, with a read-only sandbox.
2. **Findings are structured** — severity, file:line, rationale, suggested fix. They are asked for with `--json-schema` / `--output-schema`, so they are cheap to move between vendors and can be shown as a list.
3. **The fix goes into the implementer's own session when it is warm.** That means:
   - its last request is inside the cache TTL (set the 1-hour TTL on API-key workers);
   - its context is under about 100k tokens;
   - the worktree is the one it left.
   Otherwise the fix is a **fresh launch** whose briefing carries the round. Paperclip and AO resume; Anthropic's harness and ccswarm's fix stages go fresh. The policy is to resume while warm and go fresh when cold.
4. **Cap at two rounds, then escalate to a person**, and say so in the briefing, so the agent knows the last round is the last.
