"""``dplanner question ask|list|answer|escalate`` — the one question door.

An agent in a headless run asks with ``question ask``: the question is recorded on its run
(named by ``$DPLANNER_RUN``, which the supervisor sets) and the agent is told to end its turn;
the run parks on it, and the answer resumes the same session. Every harness can run a shell
command, so this door is the same for all of them. An agent in a terminal has a person at
hand: there ``question ask`` records nothing and sets ``needs-input``, as it always did.

``answer`` records an answer, which the run's supervisor delivers; ``escalate`` is the
coordinator passing a question to a person. Who acts is read from the shell: inside a run or
an agent's shell it is the coordinator, which may not answer its own run's question. None of
them commits: the window's Save does.
"""

import getpass
import os
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from pathlib import Path

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.discovery import RUN_ENV
from dplanner.cli.lookup import body_from, find_step
from dplanner.domain import ledger, questions
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import now_stamp
from dplanner.domain.questions import Question
from dplanner.modules.agent_questions import inbox
from dplanner.modules.step_agent_run.aspect import MODULE_ID, NEEDS_INPUT, launched, write
from dplanner.planning.kinds import key_of

ASKABLE = (questions.DECISION, questions.PLAN_APPROVAL, questions.BLOCKED)


def commands(*, in_agent_shell: Callable[[], bool]) -> list[CliCommand]:
    def by(args: Namespace) -> dict[str, str]:
        """Who acts, read from where the call comes from: inside a run or an agent's shell it
        is the coordinator — an agent cannot say it is a person — and elsewhere a person."""
        agent = bool(os.environ.get(RUN_ENV)) or in_agent_shell()
        kind = questions.COORDINATOR if agent else questions.PERSON
        return {"kind": kind, "name": args.by or getpass.getuser()}

    def _answer(context: CliContext, args: Namespace) -> int:
        project_dir, question = _question(context, args.question)
        try:
            done = inbox.answer(
                project_dir,
                question.id,
                " ".join(args.answer),
                by(args),
                caller_run=os.environ.get(RUN_ENV, ""),
                library=context.store.library_path,
            )
        except (LookupError, ValueError) as error:
            raise CliError(str(error)) from error
        context.report({**done.question.to_json(), "said": done.said}, done.said)
        return 0

    def _retry(context: CliContext, args: Namespace) -> int:
        project_dir = context.store.project_dir(context.project.id)
        run = _run_of(context, project_dir, args.target)
        try:
            done = inbox.retry_now(
                project_dir, run, by(args), caller_run=os.environ.get(RUN_ENV, "")
            )
        except (LookupError, ValueError) as error:
            raise CliError(str(error)) from error
        context.report({**done.question.to_json(), "said": done.said}, done.said)
        return 0

    def _escalate(context: CliContext, args: Namespace) -> int:
        project_dir, question = _question(context, args.question)
        try:
            changed = questions.update(
                project_dir,
                question.id,
                lambda q: questions.escalated(q, by(args), args.why, now_stamp()),
            )
        except (LookupError, ValueError) as error:
            raise CliError(str(error)) from error
        context.report(changed.to_json(), f"{changed.short} escalated to a person")
        return 0

    return [
        CliCommand(
            path=("question", "ask"),
            summary="Ask the developer a question from a headless run, then end your turn:"
            " the answer resumes you.",
            configure=_configure_ask,
            run=_ask,
            examples=(
                "dplanner question ask 'Keep both records?' --choice 'Keep both' --choice Absorb",
                "dplanner question ask 'Approve?' --kind plan-approval --body-file plan.md",
            ),
        ),
        CliCommand(
            path=("question", "list"),
            summary="The questions the project's runs asked, and where each stands.",
            configure=_configure_list,
            run=_list,
            examples=("dplanner question list --open",),
        ),
        CliCommand(
            path=("question", "answer"),
            summary="Answer a question; the run that asked it resumes with the answer.",
            configure=_configure_answer,
            run=_answer,
            examples=("dplanner question answer Q-e1f2 'Keep both'",),
        ),
        CliCommand(
            path=("agent", "retry"),
            summary="Retry now: resume a run held on a usage limit, or blocked, at once.",
            configure=_configure_retry,
            run=_retry,
            examples=("dplanner agent retry S12", "dplanner agent retry 20261007T101500Z-9c1e44ab"),
        ),
        CliCommand(
            path=("question", "escalate"),
            summary="Pass a question on to a person, saying why.",
            configure=_configure_escalate,
            run=_escalate,
            examples=("dplanner question escalate Q-e1f2 --why 'a product call'",),
        ),
    ]


def _configure_ask(parser: ArgumentParser) -> None:
    parser.add_argument("question", help="the question, in one sentence")
    parser.add_argument(
        "--choice",
        action="append",
        default=[],
        metavar="LABEL[=DESCRIPTION]",
        help="an answer to offer; repeat for each",
    )
    parser.add_argument("--header", default="", help="a word or two naming the question")
    parser.add_argument("--kind", choices=ASKABLE, default=questions.DECISION)
    parser.add_argument(
        "--body-file", default="", help="what the question is about: a plan (- reads stdin)"
    )
    parser.add_argument("--step", default="", help="your step, for a run in a terminal")


def _ask(context: CliContext, args: Namespace) -> int:
    project = context.project
    project_dir = context.store.project_dir(project.id)
    run = os.environ.get(RUN_ENV, "")
    record = ledger.find(project_dir, run) if run else None
    if record is None or not record.headless or record.over:
        return _needs_input(context, args, record.step if record else "")
    options = [tuple(choice.partition("=")[::2]) for choice in args.choice]
    question = questions.asked(
        record.project,
        record.step,
        now_stamp(),
        [questions.one(args.question, args.header, options)],
        kind=args.kind,
        run=record.run,
        by={
            "callsign": record.callsign,
            "harness": record.harness,
            "machine": record.machine,
            "host": record.host,
        },
        body=body_from(args.body_file) if args.body_file else "",
    )
    questions.withdraw_unsettled(project_dir, record.run, "the run asked again")
    questions.write(project_dir, question)
    context.report(
        question.to_json(),
        f"Recorded as {question.short}. End your turn now, doing nothing else;"
        " you will be resumed with the answer.",
    )
    return 0


def _needs_input(context: CliContext, args: Namespace, step_id: str) -> int:
    """A run in a terminal has its person right there: it says it needs input, as before."""
    if not (args.step or step_id):
        raise CliError("no headless run here ($DPLANNER_RUN): name your step with --step")
    step = find_step(context.library, args.step or step_id, context.current)
    context.apply(
        SetModuleDataCommand(step.id, MODULE_ID, write(NEEDS_INPUT, launched=launched(step)))
    )
    context.report(
        {"step": step.id, "state": NEEDS_INPUT, "recorded": False},
        "You are in a terminal, not a headless run: put the question to the developer here"
        " and wait for the reply.",
    )
    return 0


def _configure_list(parser: ArgumentParser) -> None:
    parser.add_argument("--open", action="store_true", help="only those still waiting on someone")
    parser.add_argument("--step", default="", help="only one step's")


def _list(context: CliContext, args: Namespace) -> int:
    project_dir = context.store.project_dir(context.project.id)
    found = questions.records(project_dir)
    if args.open:
        found = [q for q in found if not q.settled]
    if args.step:
        step = find_step(context.library, args.step, context.current)
        found = [q for q in found if q.step == step.id]
    keys = {step.id: key_of(step) for step in context.project.steps}
    lines = [
        f"{q.short}  {keys.get(q.step) or q.step[:8]:<5} {q.kind:<13} {q.state:<9} {q.text}"
        for q in found
    ]
    context.report([q.to_json() for q in found], "\n".join(lines) or "no questions")
    return 0


def _configure_answer(parser: ArgumentParser) -> None:
    parser.add_argument("question", help="Q-e1f2, or the question's id")
    parser.add_argument("answer", nargs="+", help="a choice's label, or your own words")
    _configure_by(parser)


def _configure_retry(parser: ArgumentParser) -> None:
    parser.add_argument("target", help="the run's id, or a step whose headless run is parked")
    _configure_by(parser)


def _run_of(context: CliContext, project_dir: Path, target: str) -> str:
    """The run ``target`` names: a run of the project by its id, else the step's latest
    headless run that is parked."""
    if ledger.find(project_dir, target) is not None:
        return target
    step = find_step(context.library, target, context.current)
    if not (run := inbox.parked_run(project_dir, step.id)):
        raise CliError(f"{key_of(step) or step.title} has no parked headless run")
    return run


def _configure_escalate(parser: ArgumentParser) -> None:
    parser.add_argument("question", help="Q-e1f2, or the question's id")
    parser.add_argument("--why", required=True, help="why a person must decide it")
    _configure_by(parser)


def _configure_by(parser: ArgumentParser) -> None:
    # Whether a person or the coordinator acts is read from the shell, never given here.
    parser.add_argument("--by", default="", help="your name or callsign (default: your user)")


def _question(context: CliContext, ref: str) -> tuple[Path, Question]:
    project_dir = context.store.project_dir(context.project.id)
    try:
        return project_dir, questions.resolve(project_dir, ref)
    except LookupError as error:
        raise CliError(str(error)) from error
