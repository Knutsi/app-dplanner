# Evidence: is a second agent better than an agent reviewing its own work?

*Gathered 2026-10-03. It adds to [handback-and-review.md](../2026-10-01-agent-orchestration/handback-and-review.md) and does not repeat it.*

[S] marks a claim taken from a secondary source or a search summary that was not checked against the full paper. Everything else comes from the paper's abstract or HTML page.

## In short

**Partly. And the cause is not the one the question assumes.**

No study measures fresh context, a different model and an external signal against each other in one experiment. Pieced together from separate studies, the order is:

1. **An external signal (tests, execution) does most of the work.** Without one, self-review mostly fails.
2. **A fresh context adds a small, real gain** over a second look in the same session. A subagent that shares the implementer's context is the *worst* condition tested.
3. **A different model helps only when its feedback is better.** A weaker reviewer from another vendor makes code worse.
4. **Agents talking to each other (debate) is mostly cost.** Independent samples plus a vote do the work.

**For a playbook this means:**

- The criteria gate (tests) comes first and decides.
- An LLM reviewer is a second signal on top of the tests.
- The cheapest preset — the same agent in a fresh session, with a checklist and the tests — is the control every careful preset has to beat. It is not a straw man.

## 1. Self-review with no outside signal

**It mostly fails.**

- **Huang et al., ICLR 2024:** GPT-3.5 on GSM8K fixed 7.6% of its wrong answers and broke 8.8% of its right ones — a net loss ([arXiv 2310.01798](https://arxiv.org/abs/2310.01798)).
- **Kamoi et al., TACL 2024 survey:** "no prior work demonstrates successful self-correction with feedback from prompted LLMs, except for studies in tasks that are exceptionally suited for self-correction." The bottleneck is producing good feedback, not acting on it ([ACL Anthology](https://aclanthology.org/2024.tacl-1.78/)).
- **Stechly, Valmeekam and Kambhampati:** on graph colouring, GPT-4 does *worse* when it critiques itself, partly because it invents violations in answers that were valid. Accuracy rises a lot with a sound external verifier ([NeurIPS workshop](https://mlanthology.org/neuripsw/2023/stechly2023neuripsw-gpt4/)) [S].
- **CRITIC:** take away the tool and the critique gives little or nothing ([arXiv 2305.11738](https://arxiv.org/pdf/2305.11738)) [S].
- **Song et al., ICLR 2025:** a model's ability to verify its own work grows with scale. It is real, but it is not free ([arXiv 2412.02674](https://arxiv.org/abs/2412.02674)).

## 2. In code, the signal that works is execution

- **Reflexion:** HumanEval 80.1% → 91.0%, in a loop that runs the model's own tests ([arXiv 2303.11366](https://arxiv.org/abs/2303.11366)) [S].
- **LDB:** debugging that steps through the program's execution adds up to 9.8 points ([arXiv 2402.16906](https://arxiv.org/abs/2402.16906)) [S].
- **AlphaCodium:** a test-driven flow takes CodeContests from 19% to 44% ([arXiv 2401.08500](https://arxiv.org/abs/2401.08500)) [S].
- **Olausson et al., "Is self-repair a silver bullet?", ICLR 2024:**
  - At matched cost, self-repair gains are "modest… sometimes not present at all".
  - Feedback from a stronger model or a person improves repair a lot.
  - So **the quality of the feedback is what binds** ([arXiv 2306.09896](https://arxiv.org/abs/2306.09896)).
- **Blind resampling (2026, models of 1.5–7B):** a model shown its failed attempt reproduced nearly the same program in 33–68% of retries, against 2–14% without it. This is direct evidence that seeing your own work anchors you. Starting over beat repairing below 7B ([arXiv 2607.26117](https://arxiv.org/abs/2607.26117)).

## 3. Fresh context

**Cross-Context Review** (2026; Claude Opus 4.6, 30 artifacts, 150 planted errors) measured F1 for four conditions ([arXiv 2603.12123](https://arxiv.org/html/2603.12123)):

| Condition | F1 |
|---|---|
| Review in a fresh session | 28.6% |
| One self-review in the same session | 27.1% |
| A subagent carrying the producer's context | 23.8% |
| A second review in the same session | 21.7% |

- **Robust:** fresh session versus a second same-session review (Holm-adjusted p = 0.004).
- **Not significant:** fresh session versus a single self-review (p = 0.26).

**The lesson:** a second look adds value only if the context is cleared. A subagent spawned with the implementer's context is the worst option of all. That argues against the "agent spawns its own reviewer subagent" shape.

## 4. Reading and running are complementary

- **R2E-Gym:** a verifier that executes and one that only reads each plateau at about 42–43%. Combined they reach 51%. The reading verifier "relies on stylistic features" ([arXiv 2504.07164](https://arxiv.org/abs/2504.07164)).
- **SWE-Gym:** a trained verifier choosing among candidate patches adds 11.4 points ([arXiv 2412.21139](https://arxiv.org/abs/2412.21139)).
- **SWE-RM:** a verifier that reads trajectories adds 7.6–10.4 points ([arXiv 2512.21919](https://arxiv.org/abs/2512.21919)) [S].
- **Agent-as-a-Judge:** a judge that can act agrees with human consensus 90–92% of the time, against 60–71% for a plain LLM judge ([arXiv 2410.10934](https://arxiv.org/abs/2410.10934)) [S].

**So the reviewer should be able to run the tests**, in a read-only sandbox, and should also read the code.

## 5. What makes a gate work

**Concrete criteria beat open judgement:**
- **CheckEval:** splitting criteria into yes/no questions raises agreement between judges by 0.45 ([EMNLP 2025](https://aclanthology.org/2025.emnlp-main.796/)) [S].
- **TICK:** a checklist the judge writes for itself agrees with people better than a direct score ([arXiv 2410.03608](https://arxiv.org/abs/2410.03608)) [S].
- **BitsAI-CR at ByteDance:** a rule taxonomy plus a separate filter reaches 75% precision ([arXiv 2501.15134](https://arxiv.org/abs/2501.15134)).

**Over-flagging is the common failure, more than rubber-stamping:**
- **CodeRabbit in the wild:** 31,073 comments; 36.4% accepted, 56.3% rejected (invalid, redundant, out of scope) ([arXiv 2607.03316](https://arxiv.org/abs/2607.03316)).
- **Atlassian RovoDev:** 38.7% of comments led to a change, and PR cycle time fell 30.8% ([arXiv 2601.01129](https://arxiv.org/abs/2601.01129)).
- Asked to judge code against its requirements, LLMs often call correct code defective. **Asking for explanations and fixes raises the misjudgement rate** ([arXiv 2508.12358](https://arxiv.org/abs/2508.12358)).

**Approval bias exists and is easy to trigger:**
- Misleading framing flips up to 72% of code-smell decisions ([arXiv 2607.10411](https://arxiv.org/abs/2607.10411)) [S].
- Judging is sensitive to position, verbosity and sentiment ([arXiv 2604.16790](https://arxiv.org/html/2604.16790v1)).

**What this means for a reviewer stage:**
- Do not show the reviewer the implementer's own justification.
- Ask for a verdict against a checklist.
- Make every finding carry evidence (a failing command, a file:line).
- Add a pass that tries to falsify each finding before the implementer sees it.

## 6. A lead agent, or a fixed workflow?

- **Anthropic, "Building effective agents":** add multi-step agentic systems "only when simpler solutions fall short". The evaluator-optimizer pattern fits when there are "clear evaluation standards" ([post](https://www.anthropic.com/engineering/building-effective-agents)).
- **MAST** (Cemri et al., NeurIPS 2025; 1,642 annotated traces, 14 failure modes) ([arXiv 2503.13657](https://arxiv.org/html/2503.13657)):
  - System design accounts for 33.8% of failures, inter-agent misalignment 31.7%, task verification 34.5%.
  - The largest single modes: step repetition 15.7%, unaware of stopping conditions 12.4%, disobeying the task spec 11.8%, incorrect verification 9.1%.
  - Secondary summaries quote other splits from an earlier version.
- **Google, "Towards a Science of Scaling Agent Systems"** (180 configurations):
  - Every multi-agent variant made *sequential* tasks worse, by 39–70%.
  - Independent agents amplified errors 17.2×; a central orchestrator cut that to 4.4× ([arXiv 2512.08296](https://arxiv.org/abs/2512.08296)).
- **OpenCodeReview (2026):** a fixed review pipeline (rules pick files and criteria, tools are bounded, a reflection pass tries to falsify each finding) scored SEM-F1 25.1% against an agentic reviewer's 11.6%, using 5–15× fewer tokens ([arXiv 2608.09290](https://arxiv.org/abs/2608.09290)).
- **Agentless** (a fixed localise → repair → validate pipeline) and **mini-swe-agent** (one ~100-line agent, above 74% on SWE-bench Verified) show that **the strong baseline is one agent inside a fixed outer loop** ([Agentless](https://arxiv.org/abs/2407.01489) [S], [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)).
- **No rigorous 2026 head-to-head** of an LLM lead agent against a scripted workflow on real repository tasks was found. The evidence for the lead agent is product practice (Devin, Factory Missions), not measurement.

## 7. Debate

- **"Should we be going MAD?" (ICML 2024):** debate does not reliably beat self-consistency ([arXiv 2311.17371](https://arxiv.org/abs/2311.17371)).
- **"Stop Overvaluing MAD":** debate often loses to chain-of-thought or voting. Mixing *different models* is the one thing that consistently helps ([arXiv 2502.08788](https://arxiv.org/abs/2502.08788)).
- **"Debate or Vote" (NeurIPS 2025):** majority voting explains most of the gain ([arXiv 2508.17536](https://arxiv.org/abs/2508.17536)).
- **"Talk Isn't Always Cheap":** accuracy can fall over rounds, because agents drop correct answers under pressure to conform ([arXiv 2509.05396](https://arxiv.org/abs/2509.05396)).

**For a playbook:** no A↔B argument loop. The reviewer issues findings, and the implementer either fixes each one or declines it with a reason. If the two still disagree at the cap, a person decides.
