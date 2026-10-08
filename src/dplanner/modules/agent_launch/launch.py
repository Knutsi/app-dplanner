"""Launching an agent on a step: everything ``dplanner agent run`` and the window's Run
Agent do outside the plan, in one order, so neither can launch a run the other would not.
The plan's half — the claim, and taking it back — is ``workflows.py``'s.
`docs/architecture/agents.md`'s *One launch under both surfaces* has the reasoning.

A launch is, in order, all of it under the step's launch lock (``supervisor.launching``),
so two launches of one step can never both find it free:

1. **the gate** — :func:`refusal` (the step, where it works, the branch plan) and
   :func:`unfinished_run` (a headless run not over is resumed, never launched again);
2. **where it works** — :func:`worktree_of` and :func:`place`: the step's worktree, prepared
   by git (``agent_briefing.worktree.prepare``), or the checkout for a step that works in
   place. It is the slow part — a fetch — which the window runs on a task;
3. **its files and its record** — :func:`prepare_run`: the briefing in ``prompt.md`` with
   its assets beside it, and the run's ledger record, which is the launch's intent;
4. **the claim, persisted** — ``workflows.run_agent``, applied and saved by the surface;
5. **the start** — :func:`start_run`, the follow-up once all of that is on disk: a
   supervisor for a headless run, a terminal for one a person watches. A start that fails
   takes its record back, and the surface takes the claim back (``workflows.withdraw``).

A launch interrupted between its record and its start is reconciled by
``supervisor.revive``: started while its step is still claimed, deleted once it is not.
"""

import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from dplanner.cli.main import PROG
from dplanner.core.process import detached_flags
from dplanner.domain import claims, ledger
from dplanner.domain.agents import AgentHarness
from dplanner.domain.headless import StageKind
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.locations import LocationRole
from dplanner.domain.model import Library, Step, now_stamp
from dplanner.domain.repositories import UNSET, RepositoryFacts
from dplanner.domain.store import FilesFor
from dplanner.modules.agent_briefing import worktree as where
from dplanner.modules.agent_briefing.compose import brief
from dplanner.modules.agent_briefing.instructions import instruction
from dplanner.modules.agent_briefing.prompt import AssembledPrompt, PromptPart
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.profiles import Profile, agent_command, read_profiles
from dplanner.modules.agent_supervisor import limits, supervisor
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
    branches: BranchPlan,
    today: date,
    by_project: dict[str, str] | None = None,
) -> str:
    """Why no agent can run on ``step`` here, "" when one can: the step's own facts, the
    branches its run would work between, then where it would work. A repository not checked
    out here is no refusal — Run Agent clones it, and a verb that cannot asks
    :func:`unplaced`; ``by_project`` caches the answer per project, which costs git."""
    if reason := step_refusal(library, step, files, today):
        return reason
    if branches.refusal:
        return branches.refusal
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


def unfinished_run(project_dir: Path | None, step_id: str, *, of_passes: bool = True) -> str:
    """The step's headless run that is not over yet — running or parked — or "": a run to
    resume through ``agent supervise``, never to launch a second time. A playbook's launch
    leaves out its passes' runs (``of_passes=False``): whether a pass is under way, or a crash
    left its first record behind, is the engine's to judge, under the same lock. A fenced run
    counts as over: its owner lost the step, and the new one may launch once
    :func:`stop_fenced` has ended what is left of it."""
    if project_dir is None:
        return ""
    return next(
        (
            record.run
            for record in ledger.records(project_dir)
            if record.step == step_id
            and record.headless
            and not record.over
            and not record.fence
            and (of_passes or not record.pass_)
        ),
        "",
    )


# How long ``agent run`` waits for a fenced run's supervisor to end its turn: the guards'
# grace between SIGTERM and SIGKILL, and a little more.
STOPPING_S = 15.0


def stop_fenced(project_dir: Path | None, step_id: str, wait: float = 0.0) -> str:
    """Stop what is left of every fenced, unfinished run of the step on this machine — "", or
    why the step cannot launch yet. A run whose supervisor lives is signalled and waited for
    up to ``wait`` seconds; a turn that outlived its supervisor has its process group ended
    (SIGTERM, ``wait`` as the grace, then SIGKILL). Only then does the fenced run count as over
    for :func:`unfinished_run`. A fence on a run elsewhere is that machine's to obey."""
    if project_dir is None:
        return ""
    fenced = [
        record
        for record in ledger.records(project_dir)
        if record.step == step_id and record.headless and record.fence and not record.over
    ]
    supervised = [r for r in fenced if supervisor.supervised(ledger.run_dir(r.run))]
    for record in supervised:
        supervisor.stop(project_dir, record.run, "launch", "a new owner launches the step")
    orphaned = [
        record.run
        for record in fenced
        if record not in supervised and not supervisor.end_orphaned_turn(record, wait)
    ]
    deadline = time.monotonic() + wait
    still = orphaned + [r.run for r in supervised if _still_supervised(r.run, deadline)]
    if still:
        return f"its fenced run {still[0]} is still stopping — run it again in a moment"
    return ""


def _still_supervised(run: str, deadline: float) -> bool:
    while supervisor.supervised(ledger.run_dir(run)):
        if time.monotonic() >= deadline:
            return True
        time.sleep(0.2)
    return False


def held_claim(project_dir: Path | None, step_id: str) -> tuple[str, str]:
    """The squad word and claim id holding the step now, or ("", ""): what a playbook stage's
    run launches under, since a pass goes on for whichever squad holds its step."""
    holding = claims.read_holdings(project_dir, now_stamp()).get(step_id) if project_dir else None
    if holding is None or holding.state not in claims.HOLDING:
        return "", ""
    return holding.claim.callsign, holding.claim.id


def claim_for(project_dir: Path | None, step_id: str, callsign: str = "") -> str:
    """The squad claim a run of ``callsign`` launches under — the one holding the step when it
    is that member's squad's, "" when no squad holds it — or ``ValueError`` saying why not:
    another squad holds it. Both surfaces ask before a launch, and :func:`start_run` asks
    again under the launch lock, just before anything starts."""
    if project_dir is None:
        return ""
    holding = claims.read_holdings(project_dir, now_stamp()).get(step_id)
    if holding is None or holding.state not in claims.HOLDING:
        return ""
    if claims.squad_of(callsign) != holding.claim.callsign:
        raise ValueError(
            f"it is held by squad {holding.claim.callsign} ({holding.claim.short},"
            f" {holding.state}) — launch as one of it with --callsign, or release the step"
            " first (`dplanner claim release`)"
        )
    return holding.claim.id


def headless_refusal(profile: Profile, harnesses: tuple[AgentHarness, ...]) -> str:
    """Why this profile's agent cannot run headless now; "" when it can — its account's usage
    included, which holds a new launch near or past its limit until the reset."""
    harness = launcher.harness_of(agent_command(harnesses, profile), harnesses)
    if harness is None:
        return (
            f"{profile.name}'s agent command is a custom one, and only a known agent runs headless"
        )
    if harness.headless is None:
        return f"{harness.label} has no headless mode here"
    return limits.hold(limits.account_of(harness), harness.label)


def profile_for(harness_id: str, harnesses: tuple[AgentHarness, ...]) -> Profile | None:
    """The first launch profile whose agent is ``harness_id`` and runs headless — what a
    playbook's role maps to at launch. None when no profile runs it: the role is refused,
    never swapped for the default, which may be the very agent whose work is reviewed."""
    return next(
        (
            profile
            for profile in read_profiles()
            if (harness := launcher.harness_of(agent_command(harnesses, profile), harnesses))
            is not None
            and harness.id == harness_id
            and harness.headless is not None
        ),
        None,
    )


def headless_harnesses(harnesses: tuple[AgentHarness, ...]) -> tuple[str, ...]:
    """The harnesses some profile runs headless, in the profiles' order: who a role may name."""
    found = (
        launcher.harness_of(agent_command(harnesses, profile), harnesses)
        for profile in read_profiles()
    )
    return tuple(dict.fromkeys(h.id for h in found if h is not None and h.headless is not None))


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
    stage: StageKind = StageKind.EXECUTE,
    extra: Sequence[PromptPart] = (),
    callsign: str = "",
) -> AssembledPrompt:
    """The step's briefing for ``stage``, with every referenced file path mapped through
    ``staged``, a playbook stage's ``extra`` parts read last, and the squad member it runs
    as, ``callsign``, told in its preamble."""
    remap = staged or {}
    return brief(
        library,
        step,
        briefed.files,
        facts,
        branches,
        briefed.roles,
        place=lambda path: remap.get(path, path),
        stage=stage,
        extra=extra,
        callsign=callsign,
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
class Prepared:
    """A run on disk and not yet started: its record — already in ``project_dir``'s ledger
    when there is one — its briefing, and what :func:`start_run` needs."""

    record: LedgerRecord
    text: str  # The briefing, for a surface that hands it over when nothing started.
    prompt_file: Path
    files: launcher.LaunchFiles | None  # A terminal run's wrapper; None for a headless one.
    project_dir: Path | None
    profile: Profile
    workdir: Path

    def discard(self) -> None:
        """Take the record back: no run started under it."""
        if self.project_dir is not None:
            ledger.path_for(self.project_dir, self.record).unlink(missing_ok=True)


def prepare_run(
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
    extra: Sequence[PromptPart] = (),
    dress: Callable[[LedgerRecord], LedgerRecord] = lambda record: record,
    callsign: str = "",
    claim: str = "",
) -> Prepared:
    """Write the run on ``step`` in ``workdir`` (from :func:`place`): its files and its
    record, nothing started. ``project_dir`` is where the run's ledger is; a terminal run
    with none is launched unrecorded. A playbook's stage hands its ``extra`` briefing parts
    and ``dress``es the headless record with its pass; ``callsign`` and ``claim`` say which
    squad's member runs it, under which claim. Raises ``ValueError`` for a profile that
    cannot run headless — ask :func:`headless_refusal` first — and for a headless run with
    no ledger."""
    if mode == HEADLESS and (why := headless_refusal(profile, harnesses)):
        raise ValueError(why)
    if mode == HEADLESS and project_dir is None:
        raise ValueError("a headless run is driven from its ledger record, and there is none")
    command = agent_command(harnesses, profile)
    harness = launcher.harness_of(command, harnesses)
    run = ledger.new_run_id()
    directory = ledger.run_dir(run) if mode == HEADLESS else launcher.new_run_dir()
    directory.mkdir(parents=True, exist_ok=True)
    listed = briefing(library, step, briefed, facts, branches, stage=stage, extra=extra).files
    staged = launcher.stage_assets(directory, listed, briefed.read_asset)
    text = briefing(
        library, step, briefed, facts, branches, staged, stage, extra, callsign=callsign
    ).text
    project = library.project_of(step.id)
    files = None
    if mode == HEADLESS:
        assert harness is not None
        prompt_file = directory / "prompt.md"
        prompt_file.write_text(text, encoding="utf-8", newline="\n")
        session = launcher.new_session() if harness.names_session else ""
        record = dress(
            replace(
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
    record = replace(record, callsign=callsign, claim=claim)
    if project_dir is not None:
        ledger.write(project_dir, record)
    return Prepared(record, text, prompt_file, files, project_dir, profile, workdir)


def start_run(
    prepared: Prepared, harnesses: tuple[AgentHarness, ...], library: Path | None = None
) -> str:
    """Start the prepared run — "" when it started, else why not, its record taken back.
    ``library`` is the library a headless run's turns must reach."""
    why = claim_moved(prepared) or _start(prepared, harnesses, library)
    if why:
        prepared.discard()
    return why


def claim_moved(prepared: Prepared) -> str:
    """Why the run must not start because the step's ownership changed since it was prepared
    — released, ended, superseded or taken — or "". Read under the launch lock, which a
    release takes too."""
    record = prepared.record
    try:
        now = claim_for(prepared.project_dir, record.step, record.callsign)
    except ValueError as error:
        return str(error)
    if now != record.claim:
        return "the step's claim changed while it was prepared — run it again"
    return ""


def _start(prepared: Prepared, harnesses: tuple[AgentHarness, ...], library: Path | None) -> str:
    files, workdir, profile = prepared.files, prepared.workdir, prepared.profile
    if files is None:
        assert prepared.project_dir is not None  # A headless run has a ledger: it was asked.
        try:
            supervisor.start_detached(prepared.project_dir, prepared.record.run, library=library)
        except OSError as error:
            return f"the supervisor did not start — {error.strerror or error}"
        return ""
    command = launcher.resolve_command(profile.launch_command, files, workdir)
    if command is None:
        return f"no terminal opened — check {profile.name} in Settings ▸ Agent profiles"
    if failed := launcher.spawn(command, workdir, harnesses=harnesses):
        return f"no terminal opened — {failed}"
    return ""


# -- a playbook's pass, from the window -------------------------------------------------------

START_TIMEOUT_S = 300.0  # A worktree is fetched first; past this, the launch is left to finish.


def start_pass_argv(
    library: Path | None, step_id: str, playbook_id: str, *, anyway: bool
) -> list[str]:
    """``dplanner agent run <step> --playbook <id>``: how the window starts a pass. A pass
    starts only through that verb, so its gates, its lock and its claim are never written
    twice; ``anyway`` is the person's answer to the graph gate the window asked."""
    words = ["agent", "run", step_id, "--playbook", playbook_id]
    return supervisor.dplanner_argv(library, *words, *(["--anyway"] if anyway else []))


def run_dplanner(argv: Sequence[str]) -> tuple[int, str]:
    """Run a ``dplanner`` verb to its end — its exit code and its last line, stdout on
    success, stderr on a refusal. In a session of its own, so a window closed meanwhile does
    not end a launch holding the step's launch lock; a task's body, never the GUI thread."""
    try:
        done = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=START_TIMEOUT_S,
            check=False,
            start_new_session=True,
            creationflags=detached_flags(),
        )
    except subprocess.TimeoutExpired:
        return 1, "still launching after five minutes — the Control Centre shows how it went"
    except OSError as error:
        return 1, f"dplanner did not start — {error.strerror or error}"
    said = done.stdout if done.returncode == 0 else done.stderr or done.stdout
    lines = [line.strip() for line in said.splitlines() if line.strip()]
    return done.returncode, lines[-1].removeprefix(f"{PROG}: ") if lines else ""
