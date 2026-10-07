"""``dplanner agent run <step>``: Run Agent from a terminal — the launch a director or a
daemon makes, through the same workflow the window's Run Agent calls (``workflows.py``).

Headless by default: the run is handed to a detached supervisor and the verb returns at
once, nothing waiting on it. ``--terminal`` opens the profile's terminal instead, as the
window does. Nobody is asked anything: what the window would ask a person — a prerequisite
not done, a repository to clone — is a refusal here, and ``--anyway`` is the answer to the
first. A step already running headless is refused too: its run is resumed through
``agent supervise``, never launched twice.
"""

from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step, step_arg
from dplanner.core.storage.locations import remote_label
from dplanner.domain import ledger
from dplanner.domain.agents import AgentHarness
from dplanner.domain.locations import LocationRole
from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import RepositoryFacts, repository_facts
from dplanner.modules.agent_briefing.worktree import WorktreeError, run_name_of
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.launch import (
    HEADLESS,
    TERMINAL,
    Briefed,
    headless_refusal,
    launch,
    place,
    read_absolute,
    refusal,
    unplaced,
    waiting_on,
    worktree_of,
)
from dplanner.modules.agent_launch.profiles import default_profile, profile_named, read_profiles
from dplanner.modules.agent_launch.workflows import run_agent
from dplanner.modules.agent_supervisor import supervisor
from dplanner.planning.agent import uses_worktree
from dplanner.planning.branches import BranchPlan
from dplanner.planning.kinds import key_of


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
        profile = profile_named(args.profile) if args.profile else default_profile()
        if profile is None:
            names = ", ".join(repr(each.name) for each in read_profiles())
            raise CliError(f"no launch profile is called {args.profile!r} — one of {names}")
        files = context.store.files
        if why := refusal(library, step, files, facts, today):
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
        # A run this machine lost is picked up again first, so it reads as running below.
        supervisor.revive([project_dir])
        if live := _unfinished_run(project_dir, step.id):
            raise CliError(
                f"{step.title!r} already has a headless run, {live}, that is not over — resume"
                f" a parked one with `dplanner agent supervise {live} --prompt …`"
            )
        branches = branch_plan(library, step, facts)
        try:
            workdir = place(*worktree_of(step, facts), branches)
        except WorktreeError as error:
            raise CliError(str(error)) from error
        ran = launch(
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
        if ran.refused:
            raise CliError(ran.refused)
        change = run_agent(step, today=today)
        if change.command is not None:
            context.apply(change.command)
        data = {
            "step": step.id,
            "key": key_of(step),
            "run": ran.record.run,
            "mode": args.mode,
            "profile": profile.name,
            "harness": ran.record.harness,
            "workdir": str(workdir),
            # The branch the worktree is on; "" for a step that works in the checkout.
            "branch": branches.branch_for(run_name_of(step)) if uses_worktree(step) else "",
            "session": ran.record.session,
        }
        how = "headless" if args.mode == HEADLESS else "in a terminal"
        context.report(
            data,
            f"{key_of(step)} {step.title}: run {ran.record.run} started {how} in {workdir}"
            + ("" if change.command is None else " — marked in progress"),
        )
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


def _unfinished_run(project_dir: Path, step_id: str) -> str:
    """The step's headless run that is not over yet — running or parked — or ""."""
    return next(
        (
            record.run
            for record in ledger.records(project_dir)
            if record.step == step_id and record.headless and not record.over
        ),
        "",
    )
