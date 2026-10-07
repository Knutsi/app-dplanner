"""``dplanner agent run <step>``: Run Agent from a terminal — the launch a director or a
daemon makes, in the order ``launch.py`` gives both surfaces.

Headless by default: the run is handed to a detached supervisor and the verb returns at
once, nothing waiting on it. ``--terminal`` opens the profile's terminal instead, as the
window does. Nobody is asked anything: what the window would ask a person — a prerequisite
not done, a repository to clone — is a refusal here, and ``--anyway`` is the answer to the
first. A step already running headless is refused too: its run is resumed through
``agent supervise``, never launched twice — and the step's launch lock, held from the first
check until the start, makes that true of two launches at once.

**The claim is written before anything starts.** The verb writes the run's record and
applies the claim; the run starts only once the invocation's flush has put the claim on
disk (``CliContext.after_flush``). A flush refused takes the record back
(``CliContext.unwritten``); a start that fails takes the record back and writes the claim's
withdrawal, and says so.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from contextlib import ExitStack

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step, step_arg
from dplanner.core.storage.locations import remote_label
from dplanner.domain.agents import AgentHarness
from dplanner.domain.locations import LocationRole
from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import RepositoryFacts, repository_facts
from dplanner.domain.store import StaleWorkspaceError
from dplanner.modules.agent_briefing.worktree import WorktreeError, run_name_of
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.launch import (
    HEADLESS,
    TERMINAL,
    Briefed,
    headless_refusal,
    place,
    prepare_run,
    read_absolute,
    refusal,
    start_run,
    unfinished_run,
    unplaced,
    waiting_on,
    worktree_of,
)
from dplanner.modules.agent_launch.profiles import (
    default_profile,
    problem,
    profile_named,
    read_profiles,
)
from dplanner.modules.agent_launch.workflows import run_agent, withdraw
from dplanner.modules.agent_supervisor import supervisor
from dplanner.planning.agent import uses_worktree
from dplanner.planning.branches import BranchPlan
from dplanner.planning.kinds import key_of
from dplanner.planning.status import MODULE_ID as STATUS_ID
from dplanner.planning.status import Status, stored


def _configure(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument(
        "--profile", default="", help="the launch profile to run (Settings ▸ Agent profiles)"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--headless",
        dest="mode",
        action="store_const",
        const=HEADLESS,
        help="driven by a detached supervisor, nobody watching (the default)",
    )
    modes.add_argument(
        "--terminal",
        dest="mode",
        action="store_const",
        const=TERMINAL,
        help="in the profile's terminal, as Run Agent in the window opens it",
    )
    parser.set_defaults(mode=HEADLESS)
    parser.add_argument(
        "--anyway", action="store_true", help="launch although prerequisites are not done"
    )


def commands(
    *,
    roles: tuple[LocationRole, ...],
    branch_plan: Callable[[Library, Step, RepositoryFacts | None], BranchPlan],
    harnesses: tuple[AgentHarness, ...],
) -> list[CliCommand]:
    def run(context: CliContext, args: Namespace) -> int:
        library = context.library
        step = find_step(library, args.step, context.current)
        project = library.project_of(step.id)
        project_dir = context.store.project_dir(project.id)
        facts = repository_facts(project, project_dir, context.store.checkouts())
        today = context.clock.today()
        if unreadable := problem():
            raise CliError(f"the agent profiles cannot be read: {unreadable}")
        profile = profile_named(args.profile) if args.profile else default_profile()
        if profile is None:
            names = ", ".join(repr(each.name) for each in read_profiles())
            raise CliError(f"no launch profile is called {args.profile!r} — one of {names}")
        files = context.store.files
        branches = branch_plan(library, step, facts)
        if why := refusal(library, step, files, facts, branches, today):
            raise CliError(f"{step.title!r}: {why}")
        if repository := unplaced(facts, step):
            raise CliError(
                f"{remote_label(repository)} is not checked out here — Run Agent in the window"
                " clones it"
            )
        if args.mode == HEADLESS:
            why = headless_refusal(profile, harnesses)
        else:
            why = launcher.template_refusal(profile.launch_command)
        if why:
            raise CliError(why)
        if (waiting := waiting_on(library, step, today)) and not args.anyway:
            named = ", ".join(f"{key_of(each)} {each.title!r}".strip() for each in waiting)
            raise CliError(
                f"{step.title!r} waits on work not done yet: {named} — --anyway to launch it"
            )
        # What this machine lost or left half-launched is settled first, so a run it
        # restarts reads as running below.
        supervisor.revive(
            [project_dir],
            claimed=lambda record: _claimed(library, record.step),
            library=context.store.library_path,
        )
        # Held from here until the run has started, or the run has written nothing.
        held = ExitStack()
        try:
            held.enter_context(supervisor.launching(project.id, step.id))
        except BlockingIOError:
            raise CliError(f"{step.title!r} is being launched right now — by another run") from None
        context.unwritten.append(held.close)
        if live := unfinished_run(project_dir, step.id):
            raise CliError(
                f"{step.title!r} already has a headless run, {live}, that is not over — resume"
                f" a parked one with `dplanner agent supervise {live} --prompt …`"
            )
        try:
            workdir = place(*worktree_of(step, facts), branches)
        except WorktreeError as error:
            raise CliError(str(error)) from error
        prepared = prepare_run(
            library,
            step,
            Briefed(files, read_absolute, roles),
            workdir=workdir,
            facts=facts,
            branches=branches,
            project_dir=project_dir,
            profile=profile,
            harnesses=harnesses,
            mode=args.mode,
        )
        context.unwritten.append(prepared.discard)
        before = step.module_data.get(STATUS_ID)
        change = run_agent(step, today=today)
        if change.command is not None:
            context.apply(change.command)
        data = {
            "step": step.id,
            "key": key_of(step),
            "run": prepared.record.run,
            "mode": args.mode,
            "profile": profile.name,
            "harness": prepared.record.harness,
            "workdir": str(workdir),
            # The branch the worktree is on; "" for a step that works in the checkout.
            "branch": branches.branch_for(run_name_of(step)) if uses_worktree(step) else "",
            "session": prepared.record.session,
        }

        def start() -> None:
            """The follow-up, once the claim is on disk: start the run, or take the claim
            back and say why."""
            with held:
                why = start_run(prepared, harnesses, context.store.library_path)
            if why:
                raise CliError(
                    f"{step.title!r}: no run started — {why}{_withdrawn(context, step, before)}"
                )
            how = "headless" if args.mode == HEADLESS else "in a terminal"
            context.report(
                data,
                f"{key_of(step)} {step.title}: run {prepared.record.run} started {how} in"
                f" {workdir}" + ("" if change.command is None else " — marked in progress"),
            )

        context.after_flush.append(start)
        return 0

    return [
        CliCommand(
            path=("agent", "run"),
            summary="Launch the agent on a step: its worktree, its briefing, its run record"
            " and the step in progress — headless under a supervisor (the default), or in the"
            " profile's terminal.",
            configure=_configure,
            run=run,
            examples=(
                "dplanner agent run S11",
                "dplanner agent run S11 --profile 'Codex in herdr' --terminal",
                "dplanner agent run S11 --anyway --json",
            ),
        )
    ]


def _claimed(library: Library, step_id: str) -> bool:
    """Whether the step still reads in progress — what a launch interrupted before its start
    is resumed on."""
    return library.has(step_id) and stored(library.step(step_id)) is Status.IN_PROGRESS


def _withdrawn(context: CliContext, step: Step, before: object) -> str:
    """Take the claim back — a second write, since the first is on disk — and say how it
    went, as the tail of the refusal."""
    change = withdraw(step, before if isinstance(before, dict) else None)
    if change.command is None:
        return ""
    context.marks.clear()
    context.apply(change.command)
    try:
        context.store.flush(context.marks)
    except StaleWorkspaceError as error:
        return f"; the step still reads in progress ({error}) — `dplanner status set` it back"
    return "; the step is back where it was"
