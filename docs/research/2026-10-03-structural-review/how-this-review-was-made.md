# How this review was made

*A record of who asked what and what each of us thought, on 3 and 4 October 2026. The
participants were Knut (the developer), Claude (Claude Code) and Codex (OpenAI's coding
agent). It is kept so a later reader can see the reasoning as it developed, not only where
it ended.*

## How we worked

- **Independent passes over the same tree.** Claude reviewed first. Codex reviewed Claude's
  review against the same source, without being steered. Claude then answered Codex.
- **Every claim is checked in the code.** Each one cites a `file:line`, a measurement, a
  simulation over the real composition root, or, for Codex, a one-off probe over temporary
  files.
- **Disagreements stay visible.** Each opinion keeps its own section and voice (§11 is
  Codex's, §12 is Claude's), and the report does not merge them into a single text.
- **Knut decides.** The reviews recommend and lay out options. The open questions at the end
  are his.

## The conversation

| When | Who | Question or position |
|---|---|---|
| 3 Oct | Knut | Asked for an entropy and structural review: architecture, compliance with our own rules, structure, directories, naming. Specifically (a) entropy and over-engineering, (b) bad patterns that are emerging, (c) seams that are cracking. The aim is to keep scaling and keep the modularity clean, with multiplayer and autonomous workers ahead. |
| 3 Oct | Claude | Three parallel explorers, plus measurements. The composition root holds about 1,900 lines of business logic and is touched by 36% of all commits. The step ontology is written in six places. Two bugs appear when two writers touch the same files. Persistence is shaped for one writer. |
| 3 Oct | Knut | "What is better than the composition root? It has kept scale working so far. Would another architectural pattern serve us better?" |
| 3 Oct | Claude | Keep the root, but narrow its job to wiring. The proposal is a hybrid: modules import each other's headless files along an acyclic graph, and extension points cover the many-answer questions. The event bus and the service locator are rejected. |
| 3 Oct | Knut | Asked for a report with understandable code examples, diagrams, a review of the alternatives, and the renaming laid out in detail, before deciding anything. |
| 3 Oct | Claude | The report: seven alternatives, each shown on one running example, plus renaming tables and failure modes. Simulating the hybrid found two import cycles, and each one pointed at code in the wrong place. |
| 4 Oct | Knut | "What if a new core layer held more of the domain, like estimation and statuses?" |
| 4 Oct | Claude | A `planning/` tier is a good move if it holds the ontology and nothing else. In simulation it absorbs 23 of 62 root helpers. Its main risk is creep, so it needs an admission test. |
| 4 Oct | Codex | Second opinion: the diagnosis largely holds, and the remediation needs a stronger application boundary. Six probes reproduce the bugs, plus two more defects. Codex proposes headless application actions ("units of work") shared by every writer, and asks which multiplayer authority is intended. It qualifies the single kind ranking, the state machine and the "fixed model" wording. |
| 4 Oct | Knut | Asked Claude to assess Codex's opinion on performance, v2, modularity, scaling, ease of refactoring and debugging, and not over-engineering. |
| 4 Oct | Knut | Follow-up: how would the planning tier and the units of work scale over time and fit with the modules? Rely on Python type checks and architecture checks as far as possible, because missing them causes creeping issues and entropy. |
| 4 Oct | Claude | Agrees with about 80% of the second opinion and accepts its corrections. Actions should be a per-module `actions.py` pattern rather than a layer. Facts are imported and effects are injected. Proposes enforcement by mypy (`Enum` statuses, `Unknown` as its own type, a `PlanView` protocol) and by architecture tests. Gives a reconciled order. |
| 4 Oct | Knut | "Multiplayer is not designed yet." The aim is a ladder: one person, then two people, a person and a worker, worker and worker, and "a little bit more, but not too much". The person at the window is the director, with authority over the worker. Asked what the `actions.py` pattern means. |
| 4 Oct | Claude | Proposed git as the only authority and the director rule as the collision policy. Explained the pattern as one function per thing a person or agent does. |
| 4 Oct | Knut | His design: a coordination service, linked from the plan repo, that broadcasts presence, area claims and pushes. The data format stays merge-friendly so plain git works. It starts at two people and also covers a worker with a person locally. The workflow pattern is fine as long as the context system stays. |
| 4 Oct | Claude | Agreed. Three layers: format, git, coordination. One set of events with a local and a remote transport. Claims are leases on areas the graph already names. The JSON is already one key per line; `project.dproj` and step numbers are what still collide. Renamed the pattern `workflows.py`, under the context system. Recorded in [decisions-2026-10-04.md](decisions-2026-10-04.md). |

## Where each of us stands on 4 October

- **Claude:**
  - Fix correctness first.
  - Pilot *set status* end to end: `planning/` status, `step_status/actions.py` used by both
    surfaces, and the first architecture tests.
  - Make neither the facts refactor nor the pilot wait for the multiplayer decision.
- **Codex:**
  - Fix correctness first.
  - Pilot one complete workflow through a headless action, and exercise competing writers.
  - Settle the transaction and authority boundaries before expanding cross-module imports.
  - Measure success by the cost of the next change.
- **Shared:**
  - The diagnosis.
  - The bugs come first.
  - A planning home for status, readiness, estimates and scope.
  - Pure facts can be imported.
  - Effects stay injected.
  - No message bus, no microservices.
  - On-disk ids stay stable.

## Decided on 4 October

1. **Multiplayer coordinates, and git is the only authority.** A service linked from the
   plan repo broadcasts presence, area claims and pushes. It holds no plan data.
2. **The director has authority over the worker.** When the window sets a step done, the
   agent's claim ends.
3. **`workflows.py` sits under the context system**, which stays. It was renamed from
   `actions.py`.

## Still open

- The step-number design, which is the first thing rung 2 hits.
- Whether `workflows.py` goes into CLAUDE.md after the pilot.
