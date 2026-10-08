"""Answering a question, and resuming the run that parked on it — one function, so the CLI's
``question answer`` and the Control Centre's card cannot drift.

Answering only *records* the answer. The run's supervisor delivers it: it looks for an
answered question on its run whenever it starts and before it lets go of a parked run, and
claims the resume under the run's lock and the question's. Starting one here is a nudge, never
the delivery — a supervisor still letting go refuses it and finds the answer itself. An answer
given on another machine waits in the file for the run's own machine.

**Who answers is read from where the call comes from, never claimed.** A caller inside a run
is the coordinator, whatever it says, and may not answer the question its own run asked.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from dplanner.domain import ledger, questions
from dplanner.domain.model import now_stamp
from dplanner.domain.questions import Question
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.agent_supervisor.supervisor import advance_detached, start_detached

Resume = Callable[..., None]
Advance = Callable[..., None]


@dataclass(frozen=True)
class Answered:
    question: Question
    said: str  # What became of the answer: a run resumed, or why not.


def answer(
    project_dir: Path,
    question_id: str,
    given: str,
    by: Mapping[str, str],
    *,
    caller_run: str = "",
    machine: str | None = None,
    config: Path | None = None,
    resume: Resume = start_detached,
    advance: Advance = advance_detached,
    library: Path | None = None,
) -> Answered:
    """Record ``given`` as the answer, then nudge the supervisor of the run it parks when this
    machine launched it — or, for a playbook's own question, start its pass's advance, which
    acts on it on the machine that launched the pass. ``caller_run`` is the run the caller
    works in (``$DPLANNER_RUN``); ``library`` is the one the advance must reach. Raises
    ``ValueError`` with the reason when the caller may not answer it, or it is no longer open
    to an answer."""

    def answering(question: Question) -> Question:
        if caller_run and question.run == caller_run:
            raise ValueError(f"{question.short} is your own run's question: a person answers it")
        if refused := questions.may_answer(question, by.get("kind", "")):
            raise ValueError(refused)
        answers = questions.answers_for(question, given)
        return questions.answered(question, answers, by, now_stamp())

    question = questions.update(project_dir, question_id, answering, config)
    if question.pass_ and not question.run:
        try:
            advance(question.step, library=library)
        except OSError as error:  # `playbook advance` finds the answer whenever it next runs.
            return Answered(
                question, f"{question.short} answered; its pass did not advance: {error}"
            )
        return Answered(question, f"{question.short} answered; its pass advances on it")
    why_not = resumable(project_dir, question, machine or ledger.machine_id(config))
    if why_not:
        return Answered(question, f"{question.short} answered; {why_not}")
    try:
        resume(project_dir, question.run, prompt="answer")
    except OSError as error:  # The run's supervisor finds the answer when it next starts.
        return Answered(question, f"{question.short} answered; could not start its run: {error}")
    return Answered(question, f"{question.short} answered; run {question.run} resumes with it")


def retry_now(
    project_dir: Path,
    run: str,
    by: Mapping[str, str],
    *,
    caller_run: str = "",
    machine: str | None = None,
    config: Path | None = None,
    resume: Resume = start_detached,
) -> Answered:
    """*Retry now*: resume a run parked on a usage limit or a block at once, by answering
    the question it stands on ``Retry now``. A supervisor waiting for the reset finds the
    answer within moments; with none, the nudge starts one. Raises ``ValueError`` with the
    reason for a run not parked so (:func:`retry_question`)."""
    question = retry_question(project_dir, run)
    return answer(
        project_dir,
        question.id,
        questions.RETRY_NOW,
        by,
        caller_run=caller_run,
        machine=machine,
        config=config,
        resume=resume,
    )


def retry_question(project_dir: Path, run: str) -> Question:
    """The question Retry now would answer on the run, or ``ValueError`` saying why there is
    none — a run parked on a decision is resumed by its answer, never by a retry that skips
    it."""
    record = ledger.find(project_dir, run)
    if record is None or not record.headless:
        raise ValueError(f"no headless run {run} here")
    last = record.last_turn
    if not record.parked or last is None:
        raise ValueError(f"run {run} is {'over' if record.over else 'not parked'}")
    question = questions.find(project_dir, last.question) if last.question else None
    if question is None or question.state not in (questions.OPEN, questions.ESCALATED):
        raise ValueError(f"run {run} is parked on no open question")
    if question.kind not in supervisor.RETRYABLE:
        raise ValueError(f"run {run} waits on {question.short}, a {question.kind}: answer it")
    return question


def parked_run(project_dir: Path, step_id: str) -> str:
    """The step's latest headless run when it is parked, else ""."""
    runs = [r for r in ledger.records(project_dir) if r.step == step_id and r.headless]
    return runs[-1].run if runs and runs[-1].parked else ""


def retry_refusal(project_dir: Path | None, step_id: str) -> str:
    """Why Retry now does not apply to the step's headless run, or "" when it does."""
    run = parked_run(project_dir, step_id) if project_dir is not None else ""
    if project_dir is None or not run:
        return "no headless run is parked on this step"
    try:
        retry_question(project_dir, run)
    except ValueError as refused:
        return str(refused)
    return ""


def resumable(project_dir: Path, question: Question, machine: str) -> str:
    """Why answering does not resume the question's run from here, or "" when it does."""
    if not question.run:
        return "it parks no run: whoever drives the pass acts on it"
    record = ledger.find(project_dir, question.run)
    if record is None or not record.headless:
        return f"run {question.run} is no headless run here"
    if record.machine and record.machine != machine:
        host = record.host or record.machine
        return f"run {question.run} resumes when {host}, which launched it, sees the answer"
    last = record.last_turn
    if not record.parked or last is None or last.question != question.id:
        return f"run {question.run} is not parked on it"
    return ""
