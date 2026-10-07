"""Answering a question, and resuming the run that parked on it — one function, so the CLI's
``question answer`` and the Control Centre's card cannot drift.

Answering only *records* the answer. The run's own machine consumes it: the supervisor,
started here when this is that machine and the run still stands parked on this very question.
An answer given anywhere else waits in the file for that machine to notice it.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from dplanner.domain import ledger, questions
from dplanner.domain.model import now_stamp
from dplanner.domain.questions import Question
from dplanner.modules.agent_supervisor.supervisor import start_detached

Resume = Callable[..., None]


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
    machine: str | None = None,
    config: Path | None = None,
    resume: Resume = start_detached,
) -> Answered:
    """Record ``given`` as the answer, then resume the run it parks when this machine may.
    Raises ``ValueError`` with the reason when ``by`` may not answer it, or it is no longer
    open to an answer."""

    def answering(question: Question) -> Question:
        if refused := questions.may_answer(question, by.get("kind", "")):
            raise ValueError(refused)
        answers = questions.answers_for(question, given)
        return questions.answered(question, answers, by, now_stamp())

    question = questions.update(project_dir, question_id, answering, config)
    why_not = resumable(project_dir, question, machine or ledger.machine_id(config))
    if why_not:
        return Answered(question, f"{question.short} answered; {why_not}")
    resume(project_dir, question.run, prompt="answer")
    return Answered(question, f"{question.short} answered; resuming run {question.run}")


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
