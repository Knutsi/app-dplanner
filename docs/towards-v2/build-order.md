# Build order for v2

*A suggested order for building the ideas in [notes-after-meetings.md](notes-after-meetings.md). Numbers in brackets are that note's idea numbers. Written 2026-10-01, after comparing each idea with the code at that time.*

## Where the code stands

Much of the execution track is already half built. The knowledge track is close to empty. So the order starts where the code already is.

- **A headless CLI:** it applies the same commands as the GUI (`domain/commands.py`).
- **Run Agent:** harnesses, profiles and per-step worktrees (`modules/step_agent_instruction/`, `modules/agent_*`).
- **Review rounds:** an asker and a reviewer taking turns (`modules/step_review/rounds.py`).
- **Auto-launch of due steps:** `step_agent_instruction/auto_launch.py`, which only runs while a window is open.
- **An advisory "who is working on what" record:** `domain/at_work.py`, `dplanner agent-work`.
- **Schedule, budget, estimates and token usage:** `domain/schedule.py`, `modules/time_estimates/`, `step_agent_run/usage.py`.
- **Reporting:** `dplanner report site --all`, which covers one plan repository.
- **Assets:** these exist, but run output lives in temporary directories and is never shown.
- **The knowledge track:** LLM plumbing exists but nothing uses it (`framework/llm_service.py`). `domain/plan_repo.py` is the only grouping above a project. There are no embeddings and no server.

## The order

1. **Research spike: autonomy, hand-back, budget [8].** Cheap and quick. Look at the presenter's project, and decide how work is sent back and how a run is budgeted before building anything. It shapes steps 2 and 3.
2. **Playbooks [7].** Extend review rounds and auto-launch into a chain of stages on one step, each with an **exit gate**: checks that must pass before the work moves on. It is useful on its own in the GUI today. It also supplies the constraints that make step 3 safe, because a daemon running ungated agents is the lights-out factory the note warns against.
3. **The daemon [5].** Auto-launch without the window: a long-running process that runs playbooks and claims steps through the existing agent-work record. Start with a single machine, with git as the sync.
4. **The system level [1].** Turn the plan repository (`domain/plan_repo.py`) into a *system*: its projects plus domain and architecture documents. This comes before the overview because the overview's top level is the system, and playbooks can take their guidelines from it.
5. **One floor surface: overview, resource planning, reporting, artifacts [9, 10, 11].** The meeting note already calls these "three views of one surface". Once daemons are spending compute unattended, someone has to see it. It covers:
   - an overview across all systems;
   - resource planning that counts people and daemon capacity, with usage turned into cost;
   - reporting that rolls up all of the above;
   - run outputs that are kept instead of thrown away.
6. **Multiplayer server [6].** Build it only when daemons on *several machines* collide. Until then, git plus advisory claims is enough. This puts it later than the meeting note's "5 needs 6", because claims already work without a server on one machine.
7. **The factory door [2].** Chat on top of a system's knowledge, using the existing `LLMService`. It needs step 4 to have something to talk about.
8. **Knowledge graph / RAG [3].** Only if the chat shows that plain documents and search are not enough. The meeting note itself says "valuable, perhaps".
9. **Enterprise layer [12].** Only a direction for now.

## The guiding rule

Build execution before knowledge. Steps 2 to 5 make the floor run and let people see it; steps 6 to 9 make it smarter. Each step is useful on its own when it lands. Idea [4], a production floor rather than lights-out, isn't a step because it is the framing behind the whole order.
