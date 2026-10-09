"""What a step's playbook passes did, for the person reviewing them — read, never stored.

A pass keeps no record of its own (``passes.py``), so its story is its runs and questions in
the order they were made, each said once: a work run with the summary its agent gave, a
review with its verdict and findings — each finding beside the implementer's reason where it
declined it — and every answer a person or the coordinator gave the pass's gates. This is the
one builder of those messages: the step's Playbook tab reads it, and anything that later shows
a pass's conversation should too.

A work run's summary is on its record (``LedgerRecord.summary``) for runs this build
supervised. For an older run it is read back from the run's own stream, which only the
machine that launched it has — what the typed final message said, else the final text; a
plan's is its ``plan.md``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from dplanner.domain import ledger, questions
from dplanner.domain.agents import AgentHarness, harness_by_id
from dplanner.domain.headless import StageKind, TurnEnd, stage_kind, summary_of, verdict_of
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.questions import Question
from dplanner.modules.agent_supervisor.supervisor import PLAN_FILE
from dplanner.modules.step_playbook import passes
from dplanner.modules.step_playbook.engine import Pass, grouped, pass_of
from dplanner.modules.step_playbook.passes import Choices, Standing

WORK, REVIEW, ANSWER = "work", "review", "answer"


@dataclass(frozen=True)
class Finding:
    severity: str  # "high" | "medium" | "low", or "" for a person's note.
    file: str
    line: int | None
    text: str
    evidence: str = ""
    declined: str = ""  # The implementer's reason for declining it, "" when it acted on it.

    @property
    def where(self) -> str:
        if not self.file:
            return ""
        return f"{self.file}:{self.line}" if self.line else self.file


@dataclass(frozen=True)
class Event:
    """One record of a pass, in a person's words."""

    at: str  # When it was made.
    kind: str  # WORK | REVIEW | ANSWER
    stage: str
    attempt: int
    who: str  # The harness that ran it, or who answered.
    state: str  # How it stands: "done", "running", "parked", "stopped", "answered", "open"…
    run: str = ""  # The run, for a work or review event.
    question: str = ""  # The question, for an answer.
    outcome: str = ""  # A verdict's "pass" | "changes", or the answer given.
    summary: str = ""  # What the work did, the verdict's summary, or the question asked.
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True)
class PassHistory:
    pass_id: str
    playbook: str  # Its name.
    standing: Standing
    choices: Choices
    events: tuple[Event, ...]  # Oldest first.
    runs: tuple[LedgerRecord, ...]  # Its runs, oldest first: where its work is.

    @property
    def summary(self) -> str:
        """The latest account the work gave of itself — what a reviewer reads first."""
        work = [e for e in self.events if e.kind == WORK and e.summary]
        return work[-1].summary if work else ""


def history(
    project_dir: Path,
    step_id: str,
    facts: passes.Facts,
    now: datetime,
    harnesses: Sequence[AgentHarness] = (),
    config: Path | None = None,
) -> tuple[PassHistory, ...]:
    """Every pass of the step this build can read, latest first. ``facts`` is what the plan
    says of the step (``engine.facts_of``), read where the model may be: this reads files."""
    asked = questions.records(project_dir)
    found = []
    for entries in grouped(step_id, ledger.records(project_dir), asked):
        pass_ = pass_of(entries)
        if isinstance(pass_, str):
            continue
        found.append(_read(pass_, asked, facts, now, tuple(harnesses), config))
    return tuple(reversed(found))


def _read(
    pass_: Pass,
    asked: Sequence[Question],
    facts: passes.Facts,
    now: datetime,
    harnesses: tuple[AgentHarness, ...],
    config: Path | None,
) -> PassHistory:
    runs = tuple(e for e in pass_.entries if isinstance(e, LedgerRecord))
    ids = {run.run for run in runs}
    parks = [q for q in asked if q.run and q.run in ids]
    declined = passes.declines(pass_.entries)
    events = tuple(
        _run_event(e, declined, harnesses, config)
        if isinstance(e, LedgerRecord)
        else _answer_event(e, declined)
        for e in pass_.entries
    )
    return PassHistory(
        pass_id=pass_.id,
        playbook=pass_.playbook.name,
        standing=passes.standing(pass_.playbook, pass_.settings, pass_.entries, parks, facts, now),
        choices=passes.choices(pass_.playbook, pass_.settings, pass_.entries, facts),
        events=events,
        runs=runs,
    )


def _run_event(
    run: LedgerRecord,
    declined: Mapping[tuple[str, str, int], str],
    harnesses: tuple[AgentHarness, ...],
    config: Path | None,
) -> Event:
    work = Event(
        at=run.launched,
        kind=WORK,
        stage=run.stage,
        attempt=run.attempt or 1,
        who=run.harness,
        state=_run_state(run),
        run=run.run,
    )
    if stage_kind(run.stage) is not StageKind.REVIEW:
        return replace(work, summary=_summary(run, harnesses, config))
    verdict = verdict_of(run.verdict) or {}
    listed = verdict.get("findings")
    return replace(
        work,
        kind=REVIEW,
        outcome=str(verdict.get("outcome", "")),
        summary=str(verdict.get("summary", "")),
        findings=tuple(
            _finding(f, declined.get(("run", run.run, i), ""))
            for i, f in enumerate(listed if isinstance(listed, list) else [])
            if isinstance(f, dict)
        ),
    )


def _answer_event(question: Question, declined: Mapping[tuple[str, str, int], str]) -> Event:
    """An answer to one of the pass's questions; a gate's *changes* carries its note as the
    finding the work was sent back with."""
    by = question.answer.get("by", {})
    who = (by.get("name") or by.get("kind", "")) if isinstance(by, dict) else ""
    word = passes.answer_word(question)
    changes = (
        question.purpose == passes.GATE
        and bool(word)
        and not passes.is_answer(word, passes.PASS, passes.STOP)
    )
    note = str(passes.note_of(question)["text"]) if changes else ""
    return Event(
        at=question.asked,
        kind=ANSWER,
        stage=question.stage,
        attempt=question.attempt or 1,
        who=str(who),
        state=question.state,
        question=question.short,
        outcome=passes.CHANGES if changes else word,
        summary=question.text,
        findings=(
            (Finding("", "", None, note, declined=declined.get(("question", question.id, 0), "")),)
            if changes
            else ()
        ),
    )


def _finding(raw: Mapping[str, Any], declined: str) -> Finding:
    line = raw.get("line")
    return Finding(
        severity=str(raw.get("severity", "")),
        file=str(raw.get("file", "")),
        line=line if isinstance(line, int) and line > 0 else None,
        text=str(raw.get("text", "")),
        evidence=str(raw.get("evidence", "")),
        declined=declined,
    )


def _run_state(run: LedgerRecord) -> str:
    if run.fence:
        return "taken over" if run.fence.get("why") == ledger.TAKEN_OVER else "stopped"
    last = run.last_turn
    if run.over:
        return last.end if last is not None and last.end else "ended"
    if last is None:
        return "starting"
    return f"parked ({last.end})" if last.end else "running"


def _summary(run: LedgerRecord, harnesses: tuple[AgentHarness, ...], config: Path | None) -> str:
    """The work's own account: on its record, else from this machine's copy of its run."""
    if run.summary:
        return run.summary
    directory = ledger.run_dir(run.run, config)
    if stage_kind(run.stage) is StageKind.PLAN:
        try:
            return (directory / PLAN_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            pass
    harness = harness_by_id(harnesses, run.harness)
    done = [t for t in run.turns if t.end == TurnEnd.DONE]
    if harness is None or harness.headless is None or not done:
        return ""
    try:
        with (directory / f"turn-{done[-1].n}.jsonl").open(encoding="utf-8") as stream:
            return summary_of(harness.headless.read_lines(stream))
    except OSError:
        return ""
