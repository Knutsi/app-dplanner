"""The headless runs the Agents browser lists beside the terminals: a playbook's stages and
``agent run --headless``, read from the projects' ledgers and questions — never tracked.

A terminal run is this window's to watch (``runs.py``); a headless run is its supervisor's, and
anything that wants to know how it stands reads its record. So this is a derivation and holds
nothing: each run whose record is not over, and each that ended within :data:`ENDED_LISTED`
and since the browser's *Clear ended*, with its state in the words the card's playbook strip
uses for a pass — *Waits for you · plan approval*, *Parked until 14:20* — so the two never say a
run two ways. Where a run is its pass's latest, the browser leads with the card's own phrase
(``passes.standing``, through the root); this says the rest.

Whether *Follow* and *Open Session* can act is the very reading the verbs refuse with
(``agent_supervisor.takeover``), so a greyed button and the terminal's refusal are one sentence.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dplanner.domain import ledger, questions
from dplanner.domain.agents import AgentHarness, Tokens
from dplanner.domain.headless import TurnEnd
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.questions import Question
from dplanner.modules.agent_supervisor import limits
from dplanner.modules.agent_supervisor.takeover import elsewhere, open_session_refusal

# How long a headless run that ended stays listed under *Show ended*: one that ended overnight
# is still there in the morning, as the card keeps a finished pass's strip.
ENDED_LISTED = timedelta(hours=24)


@dataclass(frozen=True)
class HeadlessRun:
    run: str
    step: str
    project_dir: Path
    directory: str  # Where it worked.
    harness: str
    callsign: str
    stage: str  # The stage id ("execute", "review-2"), "" for a run that is no playbook's.
    pass_: str
    latest_of_pass: bool  # Its pass's latest run: the one the card's strip speaks for.
    state: str  # "Running", "Waits for you · a decision", "Done": the strip's vocabulary.
    tone: str  # "" | "busy" | "warn" | "good" | "bad": the strip's tones.
    live: bool  # Not over: running, parked, or not started yet.
    launched: str
    ended: str
    activity: datetime | None  # When it last said anything.
    tokens: Tokens
    follow_refusal: str
    open_refusal: str

    @property
    def key(self) -> str:
        """Its row's key: never a terminal run's, which is a directory."""
        return f"run:{self.run}"


@dataclass(frozen=True)
class ProjectRuns:
    """One project's headless runs and its questions, as read when its records last moved."""

    project_dir: Path
    records: tuple[LedgerRecord, ...]
    asked: dict[str, Question]

    @property
    def latest(self) -> set[str]:
        """The latest run of each pass, by launch: the run the pass's standing speaks for."""
        found: dict[str, LedgerRecord] = {}
        for record in self.records:
            if record.pass_ and (
                record.pass_ not in found or record.launched >= found[record.pass_].launched
            ):
                found[record.pass_] = record
        return {record.run for record in found.values()}


def read(project_dir: Path) -> ProjectRuns:
    return ProjectRuns(
        project_dir,
        tuple(record for record in ledger.records(project_dir) if record.headless),
        {question.id: question for question in questions.records(project_dir)},
    )


def listed(
    projects: Sequence[ProjectRuns],
    harnesses: tuple[AgentHarness, ...],
    now: datetime,
    *,
    cleared: str = "",
    config: Path | None = None,
) -> list[HeadlessRun]:
    """Every headless run of these projects the browser lists, in no particular order: each
    not over, and each that ended within :data:`ENDED_LISTED` and since ``cleared``."""
    found: list[HeadlessRun] = []
    for project in projects:
        latest = project.latest
        for record in project.records:
            if not record.over or _recent(record.ended, now, cleared):
                found.append(row_of(project, record, latest, harnesses, config))
    return found


def latest_on(
    project: ProjectRuns, step: str, harnesses: tuple[AgentHarness, ...], config: Path | None = None
) -> HeadlessRun | None:
    """The step's latest headless run, however long ago: what its Step menu entries act on."""
    runs = [record for record in project.records if record.step == step]
    if not runs:
        return None
    record = max(runs, key=lambda each: each.launched)
    return row_of(project, record, project.latest, harnesses, config)


def state_of(record: LedgerRecord, asked: dict[str, Question]) -> tuple[str, str]:
    """(words, tone) for where the run stands, read from its turns and its fence."""
    last = record.last_turn
    if record.fence:
        taken = record.fence.get("why") == ledger.TAKEN_OVER
        return ("Taken over", "") if taken else ("Stopped", "bad")
    if record.over:
        end = last.end if last is not None else ""
        if end == TurnEnd.DONE:
            return "Done", "good"
        return ("Stopped", "bad") if end == TurnEnd.STOPPED else (f"Ended {end}", "bad")
    if last is None:
        return "Starting", "busy"
    if not last.end:
        return "Running", "busy"
    question = asked.get(last.question)
    held = limits.parse(last.resets) if last.end == TurnEnd.LIMIT else None
    if held is not None:
        return f"Parked until {limits.clock(held)}", ""
    if question is None:
        return f"Parked: {last.end}", "warn"
    if question.state == questions.ESCALATED:
        return "Escalated", "warn"
    return f"Waits for you · {questions.waits_for(question.kind)}", "warn"


def ago(moment: datetime | None, now: datetime) -> str:
    """How long ago, in a person's words: *12 s ago*, *4 min ago*, *2 h ago*."""
    if moment is None:
        return ""
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 60:
        return f"{seconds} s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def activity_of(record: LedgerRecord, config: Path | None = None) -> datetime | None:
    """When the run last said anything: its current stream written to, on this machine; else
    its last turn's end or start; else its launch."""
    last = record.last_turn
    if last is not None and not elsewhere(record, config):
        stream = ledger.run_dir(record.run, config) / f"turn-{last.n}.jsonl"
        try:
            return datetime.fromtimestamp(stream.stat().st_mtime, UTC)
        except OSError:
            pass
    stamp = (last.ended or last.started) if last is not None else record.launched
    return limits.parse(stamp)


def row_of(
    project: ProjectRuns,
    record: LedgerRecord,
    latest: set[str],
    harnesses: tuple[AgentHarness, ...],
    config: Path | None = None,
) -> HeadlessRun:
    state, tone = state_of(record, project.asked)
    return HeadlessRun(
        run=record.run,
        step=record.step,
        project_dir=project.project_dir,
        directory=record.directory,
        harness=record.harness,
        callsign=record.callsign,
        stage=record.stage,
        pass_=record.pass_,
        latest_of_pass=record.run in latest,
        state=state,
        tone=tone,
        live=not record.over,
        launched=record.launched,
        ended=record.ended,
        activity=activity_of(record, config),
        tokens=record.tokens,
        follow_refusal=elsewhere(record, config),
        open_refusal=open_session_refusal(record, harnesses, config),
    )


def _recent(ended: str, now: datetime, cleared: str) -> bool:
    moment = limits.parse(ended)
    if moment is None or now - moment > ENDED_LISTED:
        return False
    cut = limits.parse(cleared)
    return cut is None or moment > cut
