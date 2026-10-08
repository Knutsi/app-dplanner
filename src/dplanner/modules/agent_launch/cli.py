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

import json
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.lookup import find_step, step_arg
from dplanner.core.storage.locations import remote_label
from dplanner.domain import claims, ledger
from dplanner.domain.agents import AgentHarness, harness_by_id
from dplanner.domain.headless import StageKind
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.locations import LocationRole
from dplanner.domain.model import Library, Step
from dplanner.domain.repositories import RepositoryFacts, repository_facts
from dplanner.domain.store import StaleWorkspaceError
from dplanner.modules.agent_briefing.prompt import PromptPart
from dplanner.modules.agent_briefing.worktree import WorktreeError, mainline, run_name_of
from dplanner.modules.agent_launch import launcher
from dplanner.modules.agent_launch.launch import (
    HEADLESS,
    TERMINAL,
    Briefed,
    Prepared,
    claim_for,
    headless_harnesses,
    headless_refusal,
    held_claim,
    place,
    prepare_run,
    profile_for,
    read_absolute,
    refusal,
    start_run,
    stop_fenced,
    unfinished_run,
    unplaced,
    waiting_on,
    worktree_of,
)
from dplanner.modules.agent_launch.profiles import (
    agent_command,
    default_profile,
    problem,
    profile_named,
    read_profiles,
)
from dplanner.modules.agent_launch.workflows import run_agent, withdraw
from dplanner.modules.agent_supervisor import limits, supervisor
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
    parser.add_argument(
        "--callsign",
        default="",
        help="who runs it: a member of the squad whose claim holds the step (kettle-two)",
    )
    parser.add_argument(
        "--playbook",
        nargs="?",
        const="",
        metavar="PLAYBOOK",
        help="start a pass of a playbook instead — the step's own when none is named; the"
        " profile's agent is the implementer",
    )


class BegunPass(Protocol):
    """A pass's first record on disk, nothing started: what the claim is saved beside."""

    @property
    def said(self) -> str: ...

    def start(self) -> None:
        """Start its first run — nothing for a gate — or ``CliError``, the record taken back."""

    def discard(self) -> None:
        """Take the first record back: the claim was never saved."""


# A playbook's pass on a step, checked and its settings pinned now — or CliError — and begun in
# the placed worktree under the launch lock, every stage run by the member it names: the playbook
# engine's, handed in by the root.
StartPass = Callable[[CliContext, Step, str, str, str], Callable[[str], BegunPass]]


@dataclass(frozen=True)
class StagedRun:
    """A playbook stage's run written and not yet started: its supervisor follows."""

    prepared: Prepared
    harnesses: tuple[AgentHarness, ...]
    library: Path | None

    @property
    def run(self) -> str:
        return self.prepared.record.run

    def start(self) -> None:
        if why := start_run(self.prepared, self.harnesses, self.library):
            raise CliError(f"no run started — {why}")

    def discard(self) -> None:
        self.prepared.discard()


@dataclass(frozen=True)
class StageLauncher:
    """A playbook stage's run, launched the way ``agent run`` launches one, by the profile
    that runs the stage's harness: what the playbook engine is handed to launch with."""

    roles: tuple[LocationRole, ...]
    branch_plan: Callable[[Library, Step, RepositoryFacts | None], BranchPlan]
    harnesses: tuple[AgentHarness, ...]

    def runnable(self) -> tuple[str, ...]:
        return headless_harnesses(self.harnesses)

    def merge_target(self, context: CliContext, step: Step) -> tuple[str, str]:
        """Where the step's PR must go and come from as the plan stands now — its feature
        branch, "" when its work goes to the mainline, and the step's own branch, "" when it
        works in the checkout — or ``CliError`` when the plan refuses the step a run."""
        project = context.library.project_of(step.id)
        facts = repository_facts(
            project, context.store.project_dir(project.id), context.store.checkouts()
        )
        plan = self.branch_plan(context.library, step, facts)
        if plan.refusal:
            raise CliError(plan.refusal)
        base = plan.pr_base if plan.pr_base != mainline(facts, step) else ""
        return base, plan.branch_for(run_name_of(step)) if uses_worktree(step) else ""

    def __call__(
        self,
        context: CliContext,
        step: Step,
        *,
        kind: StageKind,
        harness: str,
        extra: Sequence[PromptPart],
        dress: Callable[[LedgerRecord], LedgerRecord],
        findings: Sequence[Mapping[str, Any]],
        directory: str,
        member: str,
    ) -> StagedRun:
        """Write the stage's run — nothing started. ``limits.HeldError`` while its account is held,
        ``CliError`` for anything else that refuses it."""
        profile = profile_for(harness, self.harnesses)
        known = harness_by_id(self.harnesses, harness)
        if profile is None or known is None:
            raise CliError(f"no launch profile runs {harness} headless — Settings ▸ Agent profiles")
        account = limits.account_of(known)
        if why := limits.hold(account, known.label):
            raise limits.HeldError(why, limits.held_until(account))
        library = context.library
        project = library.project_of(step.id)
        project_dir = context.store.project_dir(project.id)
        facts = repository_facts(project, project_dir, context.store.checkouts())
        branches = self.branch_plan(library, step, facts)
        try:
            workdir = Path(directory) if directory else place(*worktree_of(step, facts), branches)
        except WorktreeError as error:
            raise CliError(str(error)) from error
        # A pass goes on for whichever squad holds its step: the re-read before the start
        # then refuses only a change of hands while the stage was prepared.
        squad, claim = held_claim(project_dir, step.id)
        # The member keeps its callsign through every stage while its squad holds the step.
        callsign = member if squad and claims.squad_of(member) == squad else squad
        try:
            prepared = prepare_run(
                library,
                step,
                Briefed(context.store.files, read_absolute, self.roles),
                workdir=workdir,
                facts=facts,
                branches=branches,
                project_dir=project_dir,
                profile=profile,
                harnesses=self.harnesses,
                mode=HEADLESS,
                stage=kind,
                extra=extra,
                dress=dress,
                callsign=callsign,
                claim=claim,
            )
        except ValueError as error:
            raise CliError(str(error)) from error
        if findings:
            handed = ledger.run_dir(prepared.record.run) / supervisor.FINDINGS_FILE
            handed.write_text(json.dumps(list(findings)), encoding="utf-8")
        return StagedRun(prepared, self.harnesses, context.store.library_path)


def commands(
    *,
    roles: tuple[LocationRole, ...],
    branch_plan: Callable[[Library, Step, RepositoryFacts | None], BranchPlan],
    harnesses: tuple[AgentHarness, ...],
    start_pass: StartPass | None = None,
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
        if args.playbook is not None and args.mode == TERMINAL:
            why = "a playbook runs headless: its stages are a supervisor's, never a terminal"
        if why:
            raise CliError(why)
        if (waiting := waiting_on(library, step, today)) and not args.anyway:
            named = ", ".join(f"{key_of(each)} {each.title!r}".strip() for each in waiting)
            raise CliError(
                f"{step.title!r} waits on work not done yet: {named} — --anyway to launch it"
            )
        # What this machine lost or left half-launched is settled first — before anything asks
        # whether the step is free — so a run it restarts reads as running below, and one a
        # crash left behind is not mistaken for work under way.
        supervisor.revive([project_dir], library=context.store.library_path)
        begin = None
        if args.playbook is not None:
            if start_pass is None:
                raise CliError("this build has no playbook engine")
            implementer = launcher.harness_of(agent_command(harnesses, profile), harnesses)
            assert implementer is not None  # headless_refusal said it is a known harness.
            member = args.callsign.strip().lower()
            begin = start_pass(context, step, args.playbook, implementer.id, member)
        # HeldError from here until the run has started, or the run has written nothing.
        held = ExitStack()
        try:
            held.enter_context(supervisor.launching(project.id, step.id))
        except BlockingIOError:
            raise CliError(f"{step.title!r} is being launched right now — by another run") from None
        context.unwritten.append(held.close)
        try:
            claim = claim_for(project_dir, step.id, args.callsign)
        except ValueError as error:
            raise CliError(f"{step.title!r}: {error}") from None
        if stopping := stop_fenced(project_dir, step.id, wait=supervisor.STOPPING_S):
            raise CliError(f"{step.title!r}: {stopping}")
        if live := unfinished_run(project_dir, step.id, of_passes=begin is None):
            raise CliError(
                f"{step.title!r} already has a headless run, {live}, that is not over — resume"
                f" a parked one with `dplanner agent supervise {live} --prompt …`"
            )
        try:
            workdir = place(*worktree_of(step, facts), branches)
        except WorktreeError as error:
            raise CliError(str(error)) from error
        if begin is not None:
            return _begin_pass(context, step, begin, workdir, held, today)
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
            callsign=args.callsign.strip().lower(),
            claim=claim,
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
            # The lock is held through a failed start's whole rollback — the record deleted
            # and the claim's withdrawal written — so no other launch sees the claim between.
            with held:
                why = start_run(prepared, harnesses, context.store.library_path)
                back = _withdrawn(context, step, before) if why else ""
            if why:
                raise CliError(f"{step.title!r}: no run started — {why}{back}")
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
                "dplanner agent run S11 --playbook plan-execute-review-other",
                "dplanner agent run S11 --profile 'Codex in herdr' --terminal",
                "dplanner agent run S11 --anyway --json",
            ),
        )
    ]


def _begin_pass(
    context: CliContext,
    step: Step,
    begin: Callable[[str], BegunPass],
    workdir: Path,
    held: ExitStack,
    today: date,
) -> int:
    """A playbook's pass instead of one run, in a plain run's order: the pass's first record
    written, then the step claimed — unless it waits on review, where the pass starts at its
    first gate and the work is not taken up again — and only once the claim is on disk, the
    first run started, under the launch lock still. A crash between leaves a record with no
    turn, which ``supervisor.revive`` starts while the claim stands and drops when it never
    landed."""
    begun = begin(str(workdir))
    context.unwritten.append(begun.discard)
    before = step.module_data.get(STATUS_ID)
    at_review = stored(step) is Status.READY_FOR_REVIEW
    change = run_agent(step, today=today) if not at_review else None
    if change is not None and change.command is not None:
        context.apply(change.command)

    def start() -> None:
        with held:
            try:
                begun.start()
                why = ""
            except CliError as error:
                why = str(error)
            back = _withdrawn(context, step, before) if why and change is not None else ""
        if why:
            raise CliError(f"{step.title!r}: {why}{back}")
        said = begun.said
        context.report({"step": step.id, "key": key_of(step), "workdir": str(workdir)}, said)

    context.after_flush.append(start)
    return 0


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
