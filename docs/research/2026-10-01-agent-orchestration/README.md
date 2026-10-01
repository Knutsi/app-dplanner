# Research: orchestrating agents for playbooks and autonomous workers

*2026-10-01. The research spike that `docs/towards-v2/build-order.md` puts first: how agents run on their own, how they send work back and forth, and how that is budgeted. It is the groundwork for playbooks (idea 7 in `docs/towards-v2/notes-after-meetings.md`), the worker daemon (5) and the multiplayer server (6).*

## The question

The user's brief: **can DPlanner run agents headless and autonomously — on a server, or on a developer's own machine — working through a plan with playbooks in which agents pass status and findings to each other** for several rounds of review and fixes, a security review, and a person's review? The token spend should stay sensible, and humans and agents should be able to see who is working on which part of the graph. It should climb, one rung at a time, from "a planner on my laptop" to "a factory service for a company's projects".

## What is in this directory

| File | What it answers |
|---|---|
| [landscape.md](landscape.md) | How 15 orchestrators do it — six read in code (Symphony, Beads/Gas Town, Paperclip, Agent Orchestrator, Vibe Kanban, ccswarm) — with a comparison table, patterns to take and anti-patterns |
| [headless-mechanics.md](headless-mechanics.md) | The non-interactive flags of every agent CLI, what a subscription may be used for, and the security baseline for an agent nobody watches |
| [handback-and-review.md](handback-and-review.md) | Resume the implementer or start fresh, what prompt caching does to the price, the evidence on cross-vendor review, how many rounds, per-step vs per-branch review |
| [coordination.md](coordination.md) | Claims as leases, where they live at each scale, presence, and the answers to the meeting note's open questions |
| [proposal.md](proposal.md) | How DPlanner should do it, and in what order |

## Ten findings

1. **Headless is viable, and it is the only sane way.** Every agent CLI has a non-interactive mode with structured output and a session id: `claude -p --output-format stream-json`, `codex exec --json` (or the Codex App Server), `gemini -p`, `cursor-agent -p`, `opencode serve`. The orchestrators that drive terminals by `tmux send-keys` and screen-scraping (Gas Town, Claude Squad, Agent Farm) are the cautionary tales.
2. **A server runs on API keys.** Subscription login is for a person's ordinary use. Since 2026-06-15, programmatic Claude use draws on a separate API-priced credit (secondary source). A worker on the developer's own machine is the grey-zone-free case; a server is a product.
3. **The field converged on what DPlanner already does.** The better orchestrators all use the same shapes:
   - agents report through **idempotent CLI verbs** (AO's `ao review submit`, Gas Town's `gt done`);
   - a **level-triggered scheduler reconciles each tick** (Symphony);
   - **one ledger per task** carries the conversation.
   DPlanner's `review` verbs, `review_rounds` ledger and `AutoLauncher` are that design. The missing parts are a launcher without the window and harnesses without a terminal.
4. **Reviewers start fresh; fixes go back to the implementer while its cache is warm.** Paperclip and AO paste review feedback into the original session. Anthropic's long-running harness and ccswarm's fix stages go fresh. Prompt caching decides between them: a warm resume reads history at 10%, a cold one pays in full. So resume inside the TTL (set 1 h on API keys) and under ~100k tokens, and go fresh otherwise.
5. **A reviewer from another vendor helps, but only if it is at least as strong.** Each model finds more bugs in the other's code (Greptile). A weaker cross-vendor reviewer made things *worse* (arXiv 2607.21656: 13 regressions for 3 fixes). Review output is advisory, and tests gate the fix.
6. **Two rounds, then a person.** Two rounds capture 76–95% of the gain from iterating. The orchestrators that bound loops cap at three, and the ones that do not fail to converge (Yegge: Gas Town "burned down" on "just two more things").
7. **Review the branch, not every step.** A review's cost is mostly fixed context ($15–25 per PR for Claude Code Review). Reviewing the branch several parallel steps land on pays it once and sees how they fit. So: light gates per step, the careful cross-vendor playbook at the branch landing.
8. **Multi-agent works when writes stay single-threaded.** Multi-agent systems use ~15× the tokens of a chat (agent teams ~7×). The value comes from fresh judgement, not parallel writers (Cognition, 2026). One implementer plus a few reviewer passes is the shape worth paying for.
9. **Claims are leases, and hot state stays out of the plan's files.** Beads moved its claims off merged git files onto a separate ref. A lease has a TTL, a heartbeat, a reaper, a fencing epoch, and never reaps another replica's lease. Presence is ephemeral, and a CRDT is the wrong tool for a claim.
10. **Budget belongs in the scheduler.** Paperclip warns at 80% and pauses at 100%, and is the only one doing it well. Nobody else caps spend, and Gas Town ran at ~$100/h.

## The recommendation in one paragraph

**A playbook is a mark on one step** — the step looks as it does today, wrapped in a ring that names the playbook and shows its stage and round. Its stages are rounds in the `review_rounds` ledger the step already understands, gaining a `stage` key. The same stage skills serve standalone Review steps and **branch landings**, where the careful playbook reviews a whole branch before its PR. **`dplanner worker` is the window's auto-launcher without the window.** It runs harnesses through a new headless `exec` template, resumes a warm implementer for fixes, gates on a budget and shares one lock with the window. Agents keep talking through the plan with the verbs they use today. The ladder climbs:

- **L0** window and terminals;
- **L1** a local worker;
- **L2** the same worker on a server with API keys and a sandbox;
- **L3** several workers, lease claims (git refs first) and live presence;
- **L4** the factory service.

Each rung is useful on its own. [proposal.md](proposal.md) has the detail and the order.

## About the sources

Three research agents gathered this on 2026-10-01:
- one mapped DPlanner's own agent code;
- one read the orchestrators' source through the GitHub API;
- one collected CLI documentation, pricing, papers and engineering posts.

Every external claim carries its URL. Claims from search summaries or secondary write-ups are marked: the two OpenAI posts that returned 403, the June 2026 Claude credit figures, and OpenAI's 24 h cache default. The field moves monthly — Vibe Kanban, Terragon and Gas Town all shut down or were abandoned within the year — so check star counts, flags and prices before relying on them.
