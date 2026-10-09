"""``dplanner playbook …`` — which playbook a step runs, and the project's defaults.

``list`` prints the presets, ``show`` says which one a step resolves to and why, and where its
latest pass stands in the words the card's strip uses (``passes.standing``), and ``set`` writes
a step's choice — or, with no step, the project's default and landing default. None of them
runs anything: a playbook is a choice until ``agent run --playbook`` starts a pass.
``advance`` moves a pass on — what a finished stage and an answered gate start on their own,
and what a person may run to see a pass take its next step; it acts once however often it runs.
``stop`` ends a pass in whatever state it is in — Step ▸ Stop Playbook runs it as a process.
"""

import getpass
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from textwrap import indent
from typing import Protocol

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.discovery import acting
from dplanner.cli.lookup import find_step, step_arg
from dplanner.domain.agents import AgentHarness, shell_marker
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.library_file import resolve_library_path
from dplanner.domain.model import Step
from dplanner.domain.workflow import EndClaim, Release
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.step_playbook.aspect import (
    MODULE_ID,
    Choice,
    read,
    read_project,
    resolve,
    write,
    write_project,
)
from dplanner.modules.step_playbook.engine import (
    Answer,
    halted_pass,
    review_choices,
    send_back,
    standing_of,
    stop,
    wake,
)
from dplanner.modules.step_playbook.passes import PASS, describe
from dplanner.modules.step_playbook.presets import MAX_ROUNDS, PRESETS, ROUNDS, Playbook, preset
from dplanner.modules.step_playbook.workflows import ACCEPTED, acceptance, stopped
from dplanner.modules.step_status.workflows import perform
from dplanner.planning.status import Status, stored, word

DEFAULT = "default"  # `set <step> default`: the step goes back to the project's choice.
NONE = "none"  # `set --project-default none`: steps that never chose get Run Agent.

_SOURCES = {
    "step": "its own choice",
    "landing": "the project's landing default",
    "project": "the project's default",
}


class SetStatus(Protocol):
    def __call__(
        self, context: CliContext, step: Step, status: Status, because: str, titled: str
    ) -> None: ...


def commands(
    *,
    harnesses: tuple[AgentHarness, ...],
    advance: Callable[[CliContext, Step], str],
    end_claim: Callable[[EndClaim], bool],
    release: Callable[[Path, Release], bool],
    answer: Answer,
    set_status: SetStatus,
) -> list[CliCommand]:
    """``answer`` is the one answer path; ``set_status`` writes a status as ``status set``
    does, a ``because`` kept as a decision note."""

    def by(args: Namespace) -> dict[str, str]:
        return acting(args.by, bool(shell_marker(harnesses)))

    def _accept(context: CliContext, args: Namespace) -> int:
        """The pass's open gate answered *Pass*; or, a pass that is through, its step done."""
        step = find_step(context.library, args.step, context.current)
        project_dir = context.store.project_dir(context.library.project_of(step.id).id)
        pass_, chosen = review_choices(project_dir, step)
        if chosen.accept or pass_ is None:
            raise CliError(f"{step.title} cannot be accepted: {chosen.accept}")
        if chosen.gate is not None:
            said = answer(context, project_dir, chosen.gate.id, PASS, by(args))
            context.report({"step": step.id, "question": chosen.gate.id, "said": said}, said)
            return 0
        reason = acceptance(pass_.id, pass_.playbook.name, args.because or "")
        set_status(context, step, Status.DONE, reason, ACCEPTED)
        context.report(
            {"step": step.id, "status": "done", "pass": pass_.id},
            f"{step.title}: done — {reason}",
        )
        return 0

    def _send_back(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        said = send_back(context, step, args.note, by(args), answer)
        context.report({"step": step.id, "said": said}, f"{step.title}: sent back — {said}")
        return 0

    def _advance(context: CliContext, args: Namespace) -> int:
        step = find_step(context.library, args.step, context.current)
        said = advance(context, step)
        context.report({"step": step.id, "said": said}, said)
        return 0

    def _stop(context: CliContext, args: Namespace) -> int:
        """The pass stopped first, then the plan — and the plan only once nothing of the pass
        runs: the other order would let a stage that ends in between launch the next one, or
        say nobody works a step a surviving process still works. A stop whose change to the
        plan did not land, or a pass something else halted, is finished by the next. Nothing to
        stop is said, and is no error.

        The step's launch lock is held from before the stop until the plan is written and its
        follow-ups are done: a launch let in after the stop would start a pass whose step
        this plan change sets back to pending, and whose claim its release stops."""
        step = find_step(context.library, args.step, context.current)
        project = context.library.project_of(step.id).id
        project_dir = context.store.project_dir(project)
        locked = ExitStack()
        locked.enter_context(supervisor.launching(project, step.id, wait=True))
        context.unwritten.append(locked.close)
        done = stop(project_dir, step, getpass.getuser())
        if done is not None and done.still:
            raise CliError(f"{step.title}: {done.said()} — its status is left as it was")
        # The plan as it stands now, not as it was read before the step's lock came free: a
        # launch that held it may have claimed the step meanwhile.
        adopted = context.store.adopt_outside_changes()
        if adopted.deferred or adopted.rebuild_required:
            raise CliError(f"{step.title}: the plan was being written meanwhile — run it again")
        step = context.library.step(step.id)
        pass_id = done.pass_ if done is not None else halted_pass(project_dir, step)
        nothing = f"{step.title}: nothing to stop — no playbook pass runs or waits on it"
        if not pass_id:
            context.report({"step": step.id, "stopped": False}, nothing)
            context.after_flush.append(locked.close)
            return 0
        change = stopped(context.library, step, today=context.clock.today())
        if change.command is not None:
            context.apply(change.command)

        def settle() -> None:
            try:
                settled()
            finally:
                locked.close()

        def settled() -> None:
            performed = perform(
                change.follow_ups,
                end_claim,
                lambda follow_up: release(context.store.project_dir(follow_up.project), follow_up),
            )
            if (
                done is None
                and change.command is None
                and not (performed.ended or performed.failed)
            ):
                context.report({"step": step.id, "stopped": False}, nothing)
                return
            released = any(isinstance(each, Release) for each in performed.ended)
            now = word(stored(context.library.step(step.id)))
            data = {
                "step": step.id,
                "stopped": True,
                "pass": pass_id,
                "runs": list(done.runs) if done is not None else [],
                "questions": list(done.questions) if done is not None else [],
                "status": now,
                "released": released,
            }
            said = done.said() if done is not None else f"finished stopping pass {pass_id}"
            tail = (f"; it reads {now}" if change.command is not None else "") + (
                "; released from its squad's claim" if released else ""
            )
            context.report(data, f"{step.title}: {said}{tail} — its worktree and branch are kept")
            if performed.failed:
                raise CliError(
                    "; ".join(f"{type(each).__name__}: {why}" for each, why in performed.failed)
                    + " — `dplanner playbook stop` again finishes it"
                )

        context.after_flush.append(settle)
        return 0

    def _configure_set(parser: ArgumentParser) -> None:
        parser.add_argument("step", nargs="?", help="the step; omit to set a project default")
        parser.add_argument(
            "playbook", nargs="?", help=f"a preset id, or {DEFAULT!r} for the project's choice"
        )
        parser.add_argument(
            "--rounds",
            type=int,
            help=f"verdicts each gate may give before it escalates, 1 to {MAX_ROUNDS} "
            f"(default {ROUNDS})",
        )
        parser.add_argument(
            "--reviewer",
            choices=[harness.id for harness in harnesses],
            help="the agent CLI an other-agent review runs (default: another vendor's)",
        )
        parser.add_argument(
            "--project-default",
            metavar="PLAYBOOK",
            help=f"the playbook a step that never chose runs, or {NONE!r} for Run Agent",
        )
        parser.add_argument(
            "--landing-default",
            metavar="PLAYBOOK",
            help="the playbook a branch landing that never chose runs (default land)",
        )

    return [
        CliCommand(
            path=("playbook", "list"),
            summary="The playbooks a step can run, with their stages and the project's defaults.",
            run=_list,
            examples=("dplanner playbook list",),
        ),
        CliCommand(
            path=("playbook", "show"),
            summary="Which playbook a step runs, where that was chosen, and its stages.",
            configure=step_arg,
            run=_show,
            examples=("dplanner playbook show S7",),
        ),
        CliCommand(
            path=("playbook", "set"),
            summary="Choose a step's playbook, its round cap and reviewer — or, with no step, "
            "the project's default and landing default.",
            configure=_configure_set,
            run=_set,
            examples=(
                "dplanner playbook set S7 plan-execute-review-other --reviewer codex",
                "dplanner playbook set S7 default",
                "dplanner playbook set --project-default plan-execute-person",
            ),
        ),
        CliCommand(
            path=("playbook", "wake"),
            summary="Wait for a held pass's usage reset, answer its card for the clock, and"
            " advance it — what a held launch starts on its own.",
            configure=_configure_wake,
            run=_wake,
            needs_library=False,
            examples=("dplanner playbook wake Q-e1f2 --project-dir ~/plans/widget",),
        ),
        CliCommand(
            path=("playbook", "stop"),
            summary="Stop a step's playbook pass whatever it is doing — a live turn, a parked or"
            " held run, a stage between turns — so nothing of it starts again; a step in"
            " progress goes back to pending. Its worktree and branch are kept.",
            configure=step_arg,
            run=_stop,
            examples=("dplanner playbook stop S7",),
        ),
        CliCommand(
            path=("playbook", "accept"),
            summary="Accept a step's playbook pass: the gate it waits on answered Pass, or — a"
            " pass that is through — the step done, kept as a person's decision note.",
            configure=_configure_accept,
            run=_accept,
            examples=(
                "dplanner playbook accept S7",
                "dplanner playbook accept S7 --because 'read the summary and the diff'",
            ),
        ),
        CliCommand(
            path=("playbook", "send-back"),
            summary="Send a step's playbook pass back with what must change: the gate it waits"
            " on answered so, or — a pass that is through — another round of the work, the"
            " note its finding. The round cap holds.",
            configure=_configure_send_back,
            run=_send_back,
            examples=("dplanner playbook send-back S7 --note 'the empty state says nothing'",),
        ),
        CliCommand(
            path=("playbook", "advance"),
            summary="Move a step's playbook pass on: launch the stage that is due, ask its gate,"
            " or accept the work — once, however often it is run.",
            configure=step_arg,
            run=_advance,
            examples=("dplanner playbook advance S7",),
        ),
    ]


def _configure_accept(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--because", help="what the acceptance rests on, kept in the note")
    _configure_by(parser)


def _configure_send_back(parser: ArgumentParser) -> None:
    step_arg(parser)
    parser.add_argument("--note", required=True, help="what must change, in your own words")
    _configure_by(parser)


def _configure_by(parser: ArgumentParser) -> None:
    parser.add_argument("--by", default="", help="your name (default: your user name)")


def _configure_wake(parser: ArgumentParser) -> None:
    parser.add_argument("question", help="the held pass's card, by its id")
    parser.add_argument("--project-dir", required=True, help="the project directory it is in")


def _wake(context: CliContext, args: Namespace) -> int:
    """No library is held while it waits: it may be hours, and the advance opens its own."""
    said = wake(Path(args.project_dir), args.question, library=resolve_library_path(args.library))
    context.report({"question": args.question, "said": said}, said)
    return 0


def _list(context: CliContext, args: Namespace) -> int:
    defaults = read_project(context.current) if context.current is not None else None
    rows = []
    for playbook in PRESETS:
        marks = []
        if defaults is not None and defaults.default == playbook:
            marks.append("project default")
        if defaults is not None and defaults.landing == playbook:
            marks.append("landing default")
        rows.append((playbook, marks))
    text = "\n".join(
        f"{playbook.id:<26} {playbook.name}{f'  ({", ".join(marks)})' if marks else ''}\n"
        f"{'':<26} {playbook.stage_words()}"
        for playbook, marks in rows
    )
    context.report([_data(playbook) | {"defaults": marks} for playbook, marks in rows], text)
    return 0


def _show(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    resolved = resolve(step, context.library.project_of(step.id))
    choice = read(step)
    rounds = choice.rounds if choice is not None else None
    reviewer = choice.reviewer if choice is not None else None
    project_dir = context.store.project_dir(context.library.project_of(step.id).id)
    stands = standing_of(project_dir, step, datetime.now(UTC))
    now = (
        None
        if stands is None
        else {
            "id": stands.pass_id,
            "phrase": stands.phrase,
            "tone": stands.tone,
            "stage": stands.stages[stands.current] if stands.current >= 0 else None,
            "ended": stands.ended,
        }
    )
    # The pass under way, or the last one, as the card's strip says it.
    under = "" if stands is None else "\n" + indent(describe(stands), "  ")
    if resolved.playbook is None:
        context.report(
            {"step": step.id, "playbook": None, "source": resolved.source, "pass": now},
            f"{step.title}: no playbook — Run Agent{under}",
        )
        return 0
    playbook = resolved.playbook
    stages = "\n".join(
        f"  {stage_id:<12} {stage.label}"
        for stage_id, stage in zip(playbook.stage_ids(), playbook.stages, strict=True)
    )
    context.report(
        {
            "step": step.id,
            "source": resolved.source,
            "rounds": rounds if rounds is not None else ROUNDS,
            "reviewer": reviewer,
            "pass": now,
        }
        | _data(playbook),
        f"{step.title}: {playbook.name} ({playbook.id}), {_SOURCES[resolved.source]}\n"
        f"{stages}\n"
        f"  rounds {rounds if rounds is not None else f'{ROUNDS} (default)'}"
        f" · reviewer {reviewer or 'another vendor (default)'}{under}",
    )
    return 0


def _set(context: CliContext, args: Namespace) -> int:
    for_project = args.project_default is not None or args.landing_default is not None
    if for_project:
        if args.step is not None or args.rounds is not None or args.reviewer is not None:
            raise CliError("--project-default and --landing-default set the project; name no step")
        return _set_project(context, args)
    if args.step is None or args.playbook is None:
        raise CliError("name a step and a playbook, or pass --project-default/--landing-default")
    step = find_step(context.library, args.step, context.current)
    if args.playbook == DEFAULT:
        if args.rounds is not None or args.reviewer is not None:
            raise CliError("--rounds and --reviewer go with a playbook, not the default")
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, {}, label="Set Playbook"))
        context.report({"step": step.id}, f"{step.title}: the project's playbook")
        return 0
    if args.rounds is not None and not 1 <= args.rounds <= MAX_ROUNDS:
        raise CliError(f"--rounds is 1 to {MAX_ROUNDS}")
    choice = Choice(_preset(args.playbook), rounds=args.rounds, reviewer=args.reviewer)
    entry = write(choice)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, entry, label="Set Playbook"))
    context.report({"step": step.id} | entry, f"{step.title}: {choice.playbook.name}")
    return 0


def _set_project(context: CliContext, args: Namespace) -> int:
    project = context.project
    defaults = read_project(project)
    if args.project_default is not None:
        default = None if args.project_default == NONE else _preset(args.project_default)
        defaults = replace(defaults, default=default)
    if args.landing_default is not None:
        defaults = replace(defaults, landing=_preset(args.landing_default))
    entry = write_project(defaults)
    context.apply(SetModuleDataCommand(project.id, MODULE_ID, entry, label="Set Playbooks"))
    default_words = defaults.default.name if defaults.default else "none — Run Agent"
    context.report(
        {"project": project.id, "default": defaults.default and defaults.default.id}
        | {"landing": defaults.landing.id},
        f"{project.title}: default {default_words}; landing {defaults.landing.name}",
    )
    return 0


def _preset(playbook_id: str) -> Playbook:
    found = preset(playbook_id)
    if found is None:
        known = ", ".join(playbook.id for playbook in PRESETS)
        raise CliError(f"no playbook {playbook_id!r} — the presets are {known}")
    return found


def _data(playbook: Playbook) -> dict[str, object]:
    return {
        "playbook": playbook.id,
        "name": playbook.name,
        "revision": playbook.revision,
        "stages": [
            {"id": stage_id, "role": stage.role.value}
            | ({"reviewer": stage.reviewer} if stage.reviewer else {})
            for stage_id, stage in zip(playbook.stage_ids(), playbook.stages, strict=True)
        ],
        "summary": playbook.summary,
    }
