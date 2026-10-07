"""Launching an agent on a step: everything ``dplanner agent run`` and the window's Run
Agent do outside the plan, in one order, so neither can launch a run the other would not.
The plan's half — the claim — is ``workflows.py``'s, applied once the run has started.
`docs/architecture/agents.md`'s *One launch under both surfaces* has the reasoning.

A launch is, in order:

1. **where it works** — :func:`worktree_of` and :func:`place`: the step's worktree, prepared
   by git (``agent_briefing.worktree.prepare``), or the checkout for a step that works in
   place. It is apart because it is the slow part — a fetch — which the window runs on a
   task;
2. **its files and its record** — :func:`launch`: the briefing in ``prompt.md`` with its
   assets beside it, and the run's ledger record, **written before anything spawns**: the
   record is the launch's intent, so a launcher that died after the spawn left a run on
   record, never a process nobody knows of;
3. **the start** — a supervisor for a headless run (``agent_supervisor``), a terminal for
   one a person watches. A start that fails takes its record back, since no run exists;
4. **the claim** — ``workflows.run_agent``, applied by the surface only when the run
   started: a step is never claimed for a run that did not.

The refusals are here too, as plain functions of the plan and the repository facts: the
window's greyed Run Agent and the CLI's error are the same sentence.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from dplanner.domain import ledger
from dplanner.domain.agents import AgentHarness
from dplanner.domain.headless import StageKind
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.locations import LocationRole
from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import UNSET, RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.modules.agent_briefing import worktree as where
from dplanner.modules.agent_briefing.compose import brief
from dplanner.modules.agent_briefing.instructions import instruction
from dplanner.modules.agent_briefing.prompt import AssembledPrompt
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.profiles import Profile, agent_command
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.agent_usage.aspect import launch_record
from dplanner.planning.agent import enabled, no_agent, read_project, uses_worktree, workplace
from dplanner.planning.branches import BranchPlan
from dplanner.planning.kinds import key_of, works_nobody
from dplanner.planning.progression import outstanding
from dplanner.planning.schedule import status_on
from dplanner.planning.status import Unknown, readiness_of

HEADLESS = "headless"  # Driven by a supervisor; nobody watches it, and nothing waits on it.
TERMINAL = "terminal"  # In a terminal the person owns, as Run Agent has always launched.
MODES = (HEADLESS, TERMINAL)

# -- refusals --------------------------------------------------------------------------------


def unplaced(facts: RepositoryFacts, step: Step | None = None) -> str:
    """The code repository this agent would work in that this machine has no checkout of
    — what the window's Run Agent clones first — or "" when it is placed or there is none."""
    placement = where.code_placement(facts, step)
    if placement is not None and placement.root is None:
        return placement.location.repository
    return ""


def workdir_refusal(facts: RepositoryFacts, step: Step | None = None) -> str:
    """Why no agent can work where this project's code is; "" when one can. A repository
    not checked out here is a refusal only for a verb that cannot clone — Run Agent asks
    :func:`unplaced` first and clones."""
    placement = where.code_placement(facts, step)
    if placement is not None:
        label = placement.location.repository_label
        if not placement.here:
            return f"{label} is not checked out on this machine — Project ▸ Settings…"
        assert placement.root is not None
        if not placement.root.expanduser().is_dir():
            return f"the checkout of {label} is gone from {placement.root} — Project ▸ Settings…"
        return ""
    if facts.plan_root is None:
        return "the project's folder is not in a git repository"
    if facts.state == UNSET:
        return "no code repository is recorded — Project ▸ Settings…"
    return ""


def step_refusal(library: Library, step: Step, files: FilesFor, today: date) -> str:
    """Why this step has no agent run in it; "" when it has. The step's own facts."""
    if kind := works_nobody(step):
        return no_agent(kind)
    if not enabled(step):
        return "mark the step as an agent step first (Agent, in Step Details)"
    if isinstance(status := status_on(library, today)(step), Unknown):
        return f"its status ({status.word}) was written by a newer DPlanner — update to run it"
    briefed = instruction(library, step, files)
    if not briefed.body and not briefed.files and not read_project(library.project_of(step.id)):
        return "describe the step, or write an agent instruction first"
    return ""


def refusal(
    library: Library,
    step: Step,
    files: FilesFor,
    facts: RepositoryFacts,
    today: date,
    by_project: dict[str, str] | None = None,
) -> str:
    """Why no agent can run on ``step`` here, "" when one can: the step's own facts, then
    where it would work. A repository not checked out here is no refusal — Run Agent clones
    it, and a verb that cannot asks :func:`unplaced`; ``by_project`` caches the answer per
    project, which costs git."""
    if reason := step_refusal(library, step, files, today):
        return reason
    if unplaced(facts, step):
        return ""
    # A step naming a workplace of its own is asked about on its own.
    if workplace(step) or by_project is None:
        return workdir_refusal(facts, step)
    project_id = library.project_of(step.id).id
    return by_project.setdefault(project_id, workdir_refusal(facts))


def waiting_on(library: Library, step: Step, today: date) -> list[Step]:
    """The step's prerequisites it still waits on: what the window asks about before it
    launches, and what ``agent run`` refuses over unless told ``--anyway``."""
    return outstanding(library, step, readiness_of(status_on(library, today)))


def headless_refusal(profile: Profile, harnesses: tuple[AgentHarness, ...]) -> str:
    """Why this profile's agent cannot run headless; "" when it can."""
    harness = launcher.harness_of(agent_command(harnesses, profile), harnesses)
    if harness is None:
        return (
            f"{profile.name}'s agent command is a custom one, and only a known agent runs headless"
        )
    if harness.headless is None:
        return f"{harness.label} has no headless mode here"
    return ""


# -- the launch ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Briefed:
    """What the briefing of a step is made from, beside the plan: the surface's own."""

    files: FilesFor  # The store's file areas: an instruction's images are listed from them.
    read_asset: Callable[[str], bytes | None]  # Their bytes, by the path the list gives.
    roles: tuple[LocationRole, ...]  # The kinds of place a project names, for the preamble.


def read_absolute(path: str) -> bytes | None:
    """An asset's bytes by the absolute path a module's file area hands out."""
    file = Path(path)
    return file.read_bytes() if file.is_file() else None


def briefing(
    library: Library,
    step: Step,
    briefed: Briefed,
    facts: RepositoryFacts,
    branches: BranchPlan,
    staged: dict[str, str] | None = None,
) -> AssembledPrompt:
    """The step's briefing, with every referenced file path mapped through ``staged``."""
    remap = staged or {}
    return brief(
        library,
        step,
        briefed.files,
        facts,
        branches,
        briefed.roles,
        place=lambda path: remap.get(path, path),
    )


def worktree_of(step: Step, facts: RepositoryFacts) -> tuple[Path, str]:
    """The checkout the step's agent works from, and the name of its worktree under it — ""
    for a step that works in the checkout itself. Reads the plan: the GUI thread's half."""
    checkout = (where.workdir(facts, step) or Path()).expanduser()
    return checkout, where.run_name_of(step) if uses_worktree(step) else ""


def place(checkout: Path, name: str, branches: BranchPlan) -> Path:
    """Where the agent works: the worktree ``name`` under ``checkout``, prepared now, or the
    checkout itself when there is no name. Plain values only, so a task may run it. Raises
    ``worktree.WorktreeError`` with git's reason."""
    return where.prepare(checkout, name, branches) if name else checkout


@dataclass(frozen=True)
class Launched:
    """What :func:`launch` did: ``refused`` is why nothing started, "" when it did."""

    record: LedgerRecord
    text: str  # The briefing, for a surface that hands it over when nothing started.
    prompt_file: Path
    files: launcher.LaunchFiles | None  # A terminal run's wrapper; None for a headless one.
    refused: str


def launch(
    library: Library,
    step: Step,
    briefed: Briefed,
    *,
    workdir: Path,
    facts: RepositoryFacts,
    branches: BranchPlan,
    project_dir: Path | None,
    profile: Profile,
    harnesses: tuple[AgentHarness, ...],
    mode: str,
    stage: StageKind = StageKind.EXECUTE,
) -> Launched:
    """Launch the agent on ``step`` in ``workdir`` (from :func:`place`): write its files and
    its record, then start it. ``project_dir`` is where the run's ledger is; a terminal run
    with none is launched unrecorded. Raises ``ValueError`` for a profile that cannot run
    headless — ask :func:`headless_refusal` first — and for a headless run with no ledger."""
    if mode == HEADLESS and (why := headless_refusal(profile, harnesses)):
        raise ValueError(why)
    if mode == HEADLESS and project_dir is None:
        raise ValueError("a headless run is driven from its ledger record, and there is none")
    command = agent_command(harnesses, profile)
    harness = launcher.harness_of(command, harnesses)
    run = ledger.new_run_id()
    directory = ledger.run_dir(run) if mode == HEADLESS else launcher.new_run_dir()
    directory.mkdir(parents=True, exist_ok=True)
    staged = launcher.stage_assets(
        directory, briefing(library, step, briefed, facts, branches).files, briefed.read_asset
    )
    text = briefing(library, step, briefed, facts, branches, staged).text
    project = library.project_of(step.id)
    files = None
    if mode == HEADLESS:
        assert harness is not None
        prompt_file = directory / "prompt.md"
        prompt_file.write_text(text, encoding="utf-8", newline="\n")
        session = launcher.new_session() if harness.names_session else ""
        record = replace(
            launch_record(
                run=run,
                project=project.id,
                step=step.id,
                harness=harness.id,
                directory=workdir,
                session=session,
                prompt_chars=len(text),
            ),
            mode=ledger.HEADLESS,
            stage=stage,
            attempt=1,
        )
    else:
        files = launcher.prepare(
            text,
            workdir,
            agent_command=command,
            directory=directory,
            step_title=f"{key_of(step)} {step.title}".strip(),
            project_id=project.id,
            harnesses=harnesses,
            run=run,
        )
        prompt_file = files.prompt_file
        record = launch_record(
            run=run,
            project=project.id,
            step=step.id,
            harness=harness.id if harness else "",
            directory=workdir,
            session=files.session if harness is not None and harness.names_session else "",
            prompt_chars=files.prompt_chars,
        )
    if project_dir is not None:
        ledger.write(project_dir, record)
    refused = _start(record, project_dir, files, profile, workdir, harnesses)
    if refused and project_dir is not None:
        ledger.path_for(project_dir, record).unlink(missing_ok=True)
    return Launched(record, text, prompt_file, files, refused)


def _start(
    record: LedgerRecord,
    project_dir: Path | None,
    files: launcher.LaunchFiles | None,
    profile: Profile,
    workdir: Path,
    harnesses: tuple[AgentHarness, ...],
) -> str:
    """Start the run; "" when it started, else why not."""
    if files is None:
        assert project_dir is not None  # A headless launch has a ledger: `launch` asks.
        try:
            supervisor.start_detached(project_dir, record.run)
        except OSError as error:
            return f"the supervisor did not start — {error.strerror or error}"
        return ""
    command = launcher.resolve_command(profile.launch_command, files, workdir)
    if command is None:
        return f"no terminal opened — check {profile.name} in Settings ▸ Agent profiles"
    if failed := launcher.spawn(command, workdir, harnesses=harnesses):
        return f"no terminal opened — {failed}"
    return ""
