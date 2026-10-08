"""The playbook engine: start a pass on a step, and advance it — once — whenever it moves.

Nothing waits. A pass moves when one of its stages ends or one of its questions is answered,
and each of those starts ``dplanner playbook advance <step>`` in a process of its own (the
supervisor and the answer, through ``supervisor.advance_detached``). An advance reads the
pass's records, asks :func:`~.passes.due` what is due, and does it under the step's launch
lock: launch the stage's run, ask the gate's question, accept the work on its branch, or
finish. Whatever it writes first — the run's record before its process, the next record
before the answer it acted on is marked consumed — is what the next reading finds, so an
advance repeated, or two started at once, acts once.

The launch itself is ``agent_launch``'s and the merge ``github``'s; the composition root
hands both in (:class:`StageLauncher`, :data:`Accept`), since a module reaches another's
effects only that way.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from dplanner.cli import CliContext, CliError
from dplanner.domain import ledger, questions
from dplanner.domain.headless import StageKind, TurnEnd
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.model import Step, now_stamp
from dplanner.domain.questions import Question
from dplanner.modules.agent_briefing.prompt import PromptPart
from dplanner.modules.agent_briefing.stages import approved_part, findings_part, review_part
from dplanner.modules.agent_supervisor import limits, supervisor
from dplanner.modules.step_playbook import passes
from dplanner.modules.step_playbook.aspect import read, resolve
from dplanner.modules.step_playbook.passes import (
    ESCALATION,
    GATE,
    GATE_OPTIONS,
    REFUSED_OPTIONS,
    Ask,
    Complete,
    Facts,
    Halted,
    Launch,
    Next,
    Progress,
    Settings,
    Standing,
    Wait,
)
from dplanner.modules.step_playbook.presets import Playbook, preset
from dplanner.modules.step_playbook.workflows import approved
from dplanner.planning.status import Status, stored


class Staged(Protocol):
    """A stage's run written and not yet started."""

    @property
    def run(self) -> str: ...

    def start(self) -> None:
        """Start its supervisor, or ``CliError`` — its record taken back."""

    def discard(self) -> None:
        """Take its record back."""


class StageLauncher(Protocol):
    """What the engine needs of the launch: who can run here, and a stage's run written."""

    def runnable(self) -> tuple[str, ...]:
        """The harnesses some launch profile runs headless: what a role may name."""
        ...

    def merge_target(self, context: CliContext, step: Step) -> tuple[str, str]:
        """Where the step's PR must go and come from as the plan stands now: its feature
        branch ("" for the mainline) and its own branch. ``CliError`` when the plan refuses."""
        ...

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
        claim: str,
    ) -> Staged:
        """Write the stage's run, nothing started — run by ``member`` of the squad holding the
        step when it is one of that squad's (``kettle-two``), under ``claim``, the claim the
        pass started under ("" for none). ``limits.HeldError`` while its account is held,
        ``CliError`` for any other refusal — ``claim`` ended or no longer holding the step
        among them."""
        ...


# `progress`: merge the step's PR from its own branch into its feature branch — both as the
# plan says now — and accept it. ("", False) when it was accepted; else why not, and whether
# the work goes to the mainline, which a person merges.
Accept = Callable[[CliContext, Step, str, str], tuple[str, bool]]


@dataclass(frozen=True)
class Planned:
    """A pass about to begin: checked, its settings pinned, nothing written."""

    pass_: str
    playbook: Playbook
    settings: Settings
    member: str  # The squad member it runs as, from `agent run --callsign`; "" for none.


@dataclass(frozen=True)
class Begun:
    """What acting wrote, and what follows it: a run to start, or nothing."""

    said: str
    staged: Staged | None = None
    question: Path | None = None  # A question it wrote, which discard takes back.

    def start(self) -> None:
        if self.staged is not None:
            self.staged.start()

    def discard(self) -> None:
        if self.staged is not None:
            self.staged.discard()
        if self.question is not None:
            self.question.unlink(missing_ok=True)


@dataclass(frozen=True)
class Engine:
    launch: StageLauncher
    accept: Accept

    def plan(self, context: CliContext, step: Step, chosen: str, implementer: str) -> Planned:
        """A new pass of ``chosen`` (or the step's own playbook) on ``step``, the work stages
        run by ``implementer``'s harness — or ``CliError`` saying why it cannot begin."""
        project = context.library.project_of(step.id)
        if why := active(context.store.project_dir(project.id), step):
            raise CliError(f"{step.title!r} {why}")
        playbook = preset(chosen) if chosen else resolve(step, project).playbook
        if playbook is None:
            raise CliError(
                f"no playbook {chosen!r}"
                if chosen
                else f"{step.title!r} has no playbook — name one, or `dplanner playbook set` it"
            )
        try:
            settings = passes.pinned(playbook, read(step), implementer, self.launch.runnable())
        except ValueError as error:
            raise CliError(f"{playbook.name}: {error}") from error
        return Planned(ledger.new_run_id(), playbook, settings, "")

    def start(
        self, context: CliContext, step: Step, chosen: str, implementer: str, member: str = ""
    ) -> Callable[[str], Begun]:
        """``agent run --playbook``'s half: :meth:`plan` now, and :meth:`begin` — handed the
        worktree, under the launch lock — before the claim is saved. ``member`` is the
        callsign every stage of the pass runs as."""
        planned = replace(self.plan(context, step, chosen, implementer), member=member)
        return lambda directory: self.begin(context, step, planned, directory)

    def begin(self, context: CliContext, step: Step, planned: Planned, directory: str) -> Begun:
        """Write the pass's first record — its first run, or its first gate's question — and
        start nothing: the caller saves its claim, then starts it (S11's launch order). The
        caller holds the step's launch lock. A refusal here refuses the launch."""
        project_dir = context.store.project_dir(context.library.project_of(step.id).id)
        if why := active(project_dir, step):
            raise CliError(f"{step.title!r} {why}")
        latest = _latest_pass(project_dir, step.id)
        if not isinstance(latest, str) and (orphan := _orphan(latest, step)) is not None:
            ledger.path_for(project_dir, orphan).unlink(missing_ok=True)
        pass_ = _Pass(
            planned.pass_, planned.playbook, planned.settings, [], directory, member=planned.member
        )
        next_ = passes.due(pass_.playbook, pass_.settings, [], _facts(step))
        try:
            return self._do(context, step, pass_, next_)
        except limits.HeldError as held:
            raise CliError(str(held)) from held

    def advance(self, context: CliContext, step: Step) -> str:
        """Do what the step's latest pass needs next, once; what was done, in a sentence."""
        project = context.library.project_of(step.id)
        project_dir = context.store.project_dir(project.id)
        with supervisor.launching(project.id, step.id, wait=True):
            pass_ = _latest_pass(project_dir, step.id)
            if isinstance(pass_, str):
                return f"{step.title}: {pass_}"
            here = ledger.machine_id()
            if pass_.machine and pass_.machine != here:
                return f"{step.title}: pass {pass_.id} advances on the machine that launched it"
            if _lapsed(project_dir, pass_):
                pass_ = _latest_pass(project_dir, step.id)
                assert not isinstance(pass_, str)
            next_ = passes.due(pass_.playbook, pass_.settings, pass_.entries, _facts(step))
            said = self._act(context, step, pass_, next_)
            if not isinstance(next_, Wait):
                _settle_answers(project_dir, pass_)
            return f"{step.title}: {said}"

    # -- acting -----------------------------------------------------------------------------

    def _act(self, context: CliContext, step: Step, pass_: "_Pass", next_: Next) -> str:
        """Do it, and start what it wrote — or, when the pass could not, ask about it on a
        card the pass waits on: a held account until its reset, anything else until a
        person's *Retry now*."""
        stage = next_.stage if isinstance(next_, Launch | Progress) else ""
        attempt = next_.attempt if isinstance(next_, Launch) else 1
        try:
            begun = self._do(context, step, pass_, next_)
            begun.start()
            return begun.said
        except limits.HeldError as held:
            return _refused(context, step, pass_, stage, attempt, str(held), held.until)
        except CliError as error:
            return _refused(context, step, pass_, stage, attempt, str(error), None)

    def _do(self, context: CliContext, step: Step, pass_: "_Pass", next_: Next) -> Begun:
        match next_:
            case Wait(why) | Halted(why):
                return Begun(why)
            case Complete(why, set_done):
                if set_done:
                    change = approved(step, today=context.clock.today())
                    if change.command is not None:
                        context.apply(change.command)
                        return Begun(f"{why} — the step is done")
                return Begun(why)
            case Launch():
                staged = self.launch(
                    context,
                    step,
                    kind=next_.kind,
                    harness=next_.harness,
                    extra=_parts(next_),
                    dress=pass_.dress(next_),
                    findings=[f["ref"] for f in next_.findings if "ref" in f],
                    directory=pass_.directory,
                    member=pass_.member,
                    claim=pass_.claim,
                )
                said = f"{next_.stage} (attempt {next_.attempt}) launched as run {staged.run}"
                return Begun(said, staged=staged)
            case Ask():
                return _asked(context, step, pass_, next_)
            case Progress(stage):
                why, mainline = self.accept(context, step, *self.launch.merge_target(context, step))
                if not why:
                    return Begun("accepted on its branch")
                if not mainline:
                    raise CliError(f"progress could not accept the work: {why}")
                # On the mainline the stage is a person's gate: only a person merges there.
                return _asked(
                    context,
                    step,
                    pass_,
                    Ask(
                        stage,
                        1
                        + sum(
                            1 for e in pass_.entries if isinstance(e, Question) and e.stage == stage
                        ),
                        GATE,
                        questions.DECISION,
                        f"Progress does not merge this: {why}. Does the work pass?",
                        GATE_OPTIONS,
                    ),
                )


@dataclass
class _Pass:
    id: str
    playbook: Playbook
    settings: Settings
    entries: list[passes.Entry]
    directory: str  # Where its stages work: the worktree its first run was placed in.
    machine: str = ""  # The machine that launched it, the one that advances it.
    member: str = ""  # The squad member its runs go as, as its first run recorded it.
    claim: str = ""  # The claim it runs under, as its first run recorded it: pinned.

    def first(self) -> bool:
        return not self.entries

    def dress(self, launch: Launch) -> Callable[[LedgerRecord], LedgerRecord]:
        """The run's record as the pass writes it: its pass, stage and attempt, the session a
        work stage resumes, and — on the pass's first record — its settings."""
        first = self.first()
        session = launch.resume.session if launch.resume is not None else ""

        def dressed(record: LedgerRecord) -> LedgerRecord:
            return replace(
                record,
                launched=precise_stamp(),
                playbook=self.playbook.id,
                pass_=self.id,
                stage=launch.stage,
                attempt=launch.attempt,
                session=session or record.session,
                settings=self.settings.to_json() if first else None,
            )

        return dressed


def precise_stamp() -> str:
    """Now, to the microsecond: a pass's records are read in the order they were made, and
    two made in one second must still say which came first."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _facts(step: Step) -> Facts:
    status = stored(step)
    return Facts(done=status is Status.DONE, at_review=status is Status.READY_FOR_REVIEW)


def _parts(launch: Launch) -> tuple[PromptPart, ...]:
    """What the stage hands its agent beside the step's own briefing."""
    if launch.kind is StageKind.REVIEW:
        return (review_part(launch.history),)
    parts = []
    if launch.plan is not None:
        parts.append(approved_part(_plan_text(launch.plan)))
    if launch.findings:
        parts.append(findings_part(launch.findings))
    return tuple(parts)


def _plan_text(run: LedgerRecord) -> str:
    try:
        return (ledger.run_dir(run.run) / supervisor.PLAN_FILE).read_text(encoding="utf-8")
    except OSError:
        return ""


def _ask(context: CliContext, step: Step, pass_: _Pass, ask: Ask) -> Question:
    """Write the pass's question; it."""
    project = context.library.project_of(step.id)
    project_dir = context.store.project_dir(project.id)
    question = questions.asked(
        project.id,
        step.id,
        precise_stamp(),
        [questions.one(ask.text, ask.stage.capitalize(), ask.options)],
        kind=ask.kind,
        by={"machine": ledger.machine_id(), "host": ledger.host_name()},
        body=ask.body or (_plan_text(ask.plan) if ask.plan is not None else ""),
        pass_=pass_.id,
        stage=ask.stage,
        attempt=ask.attempt,
        purpose=ask.purpose,
        settings=pass_.settings.to_json() if pass_.first() else None,
        resets=ask.resets,
    )
    questions.write(project_dir, question)
    return question


def _refused(
    context: CliContext,
    step: Step,
    pass_: _Pass,
    stage: str,
    attempt: int,
    why: str,
    until: datetime | None,
) -> str:
    """The card a pass waits on when it could not act: ``limit`` with the reset for a held
    account — the clock answers it then (:func:`wake`) — else ``blocked``; *Retry now*
    answers either, and the pass does again what it could not."""
    asked = _ask(
        context,
        step,
        pass_,
        Ask(
            stage,
            attempt,
            ESCALATION,
            questions.LIMIT if until is not None else questions.BLOCKED,
            f"The pass could not go on: {why}",
            REFUSED_OPTIONS,
            resets=until.isoformat() if until is not None else "",
        ),
    )
    if until is not None:
        project_dir = context.store.project_dir(asked.project)
        supervisor.wake_detached(project_dir, asked.id, library=context.store.library_path)
    return f"{stage} could not go on, and asks {asked.short}: {why}"


def _asked(context: CliContext, step: Step, pass_: _Pass, ask: Ask) -> Begun:
    """The pass's question written, as an act: discarding it takes the file back."""
    asked = _ask(context, step, pass_, ask)
    path = questions.path_for(context.store.project_dir(asked.project), asked)
    return Begun(f"{ask.stage} asks {asked.short} ({ask.purpose})", question=path)


def _settle_answers(project_dir: Path, pass_: _Pass) -> None:
    """Mark consumed every answer of the pass that has been acted on — after the act, so a
    crash between leaves an answer to act on again, never one lost."""
    for entry in pass_.entries:
        if isinstance(entry, Question) and entry.state == questions.ANSWERED:
            questions.update(
                project_dir,
                entry.id,
                lambda q: (
                    questions.settled_by_pass(q, precise_stamp())
                    if q.state == questions.ANSWERED
                    else q
                ),
            )


def active(project_dir: Path, step: Step) -> str:
    """Why the step's latest pass has not reached its end, or "": a step has one pass at a
    time, and a new one never quietly replaces it. A pass ends when what is due is that it is
    complete or halted — done, stopped, or given up by a person; until then it is under way,
    between stages too, while a finished stage waits for its advance. A launch that died
    before its claim was saved (:func:`_orphan`) left no pass."""
    pass_ = _latest_pass(project_dir, step.id)
    if isinstance(pass_, str) or _orphan(pass_, step):
        return ""
    next_ = passes.due(pass_.playbook, pass_.settings, pass_.entries, _facts(step))
    if isinstance(next_, Complete | Halted):
        return ""
    return f"has a playbook pass under way ({pass_.id}): {_under_way(next_)}"


# Why a stop fences a pass's runs and withdraws its questions, as the run and the card say.
STOP_WHY = "the playbook was stopped"


def stoppable(project_dir: Path, step: Step) -> str:
    """What stopping the step's latest pass would end, in a person's words — *its execute
    stage is running* — or "" when nothing of it is left to stop. Read from its raw records,
    by pass id alone, so a pass whose preset this build does not know is stopped all the
    same: a run not over, a question not settled — an answer no advance has acted on yet
    included — or a stage done whose advance is still to come. A run still dying after an
    earlier stop counts, so stopping again finishes it; so does a halted pass whose step
    still reads in progress — a stop whose change to the plan did not land, or a pass
    something else halted."""
    entries = _latest_entries(project_dir, step.id)
    if said := _left(project_dir, step.id, _facts(step), entries):
        return said
    if halted_pass(project_dir, step) and stored(step) is Status.IN_PROGRESS:
        return "it has halted, but the step still reads in progress"
    return ""


def _left(project_dir: Path, step_id: str, facts: Facts, entries: Sequence[passes.Entry]) -> str:
    runs = [e for e in entries if isinstance(e, LedgerRecord)]
    if left := [r for r in runs if not r.over]:
        run = left[-1]
        return f"its {run.stage} stage is {'still stopping' if run.fence else _run_state(run)}"
    if asked := [e for e in entries if isinstance(e, Question) and not e.settled]:
        question = asked[-1]
        if question.state == questions.ANSWERED:
            return f"its {question.stage} stage's answer to {question.short} is not acted on yet"
        return f"its {question.stage} stage waits on {question.short}"
    latest = entries[-1] if entries else None
    if not isinstance(latest, LedgerRecord) or latest.fence:
        return ""
    if latest.last_turn is None or latest.last_turn.end != TurnEnd.DONE:
        return ""
    pass_ = _latest_pass(project_dir, step_id)
    if not isinstance(pass_, str):
        next_ = passes.due(pass_.playbook, pass_.settings, pass_.entries, facts)
        if isinstance(next_, Complete | Halted):
            return ""
    return f"its {latest.stage} stage is {_run_state(latest)}"


def halted_pass(project_dir: Path, step: Step) -> str:
    """The id of the step's latest pass when it has halted — whoever fenced it, and why —
    with nothing of it left to stop, and nothing of the step has run since: what a stop
    repeated still finishes in the plan. "" otherwise, a completed pass included."""
    entries = _latest_entries(project_dir, step.id)
    facts = _facts(step)
    if not entries or _left(project_dir, step.id, facts, entries):
        return ""
    pass_ = _latest_pass(project_dir, step.id)
    if not isinstance(pass_, str) and isinstance(
        passes.due(pass_.playbook, pass_.settings, pass_.entries, facts), Complete
    ):
        return ""
    others = [r for r in ledger.records(project_dir) if r.step == step.id and not r.pass_]
    runs = [e for e in entries if isinstance(e, LedgerRecord)]
    asked = [e for e in entries if isinstance(e, Question)]
    return entries[-1].pass_ if passes.in_order([*others, *runs], asked)[-1].pass_ else ""


@dataclass(frozen=True)
class Stopped:
    """What a stop ended: the pass, its runs as they stood, the questions it withdrew, the
    runs here still stopping, and whether a run of it is another machine's to stop."""

    pass_: str
    runs: tuple[str, ...]
    questions: tuple[str, ...]
    still: tuple[str, ...]
    elsewhere: bool

    def said(self) -> str:
        parts = [f"stopped pass {self.pass_}"]
        if self.runs:
            parts.append(", ".join(self.runs))
        if self.questions:
            parts.append(f"withdrew {', '.join(self.questions)}")
        if self.still:
            parts.append(
                f"run {self.still[0]} is still stopping — `dplanner playbook stop` again ends it"
            )
        if self.elsewhere:
            parts.append("a run on another machine stops when its fence reaches it")
        return "; ".join(parts)


def stop(
    project_dir: Path, step: Step, by: str, wait: float = supervisor.STOPPING_S
) -> Stopped | None:
    """Stop the step's latest pass, whatever state it is in, so that nothing of it starts
    again by itself — or None when nothing of it is left to stop (:func:`_left`).

    The caller holds the step's launch lock, waited for, from before this reading until what
    it writes after — the plan's change, and its follow-ups — is done: a launch holding it
    may be about to write the pass's first record, and a launch let in between would start a
    pass the stop's plan change then resets and its release stops. Every question of the
    pass not yet settled is withdrawn, and every unfinished run of the pass — and its latest
    run when that ended between stages — is fenced and stopped (``supervisor.stop_and_wait``:
    a live turn signalled, a parked, unstarted or orphaned run ended here, whatever carries
    the run killed). Each of those makes :func:`~.passes.due` read the pass ``Halted``. Its
    worktree and branch are kept."""
    entries = _latest_entries(project_dir, step.id)
    return _halt(project_dir, step.id, entries, _facts(step), by, STOP_WHY, wait)


def halt_claimed(
    project_dir: Path, step_id: str, claim_id: str, by: str, why: str
) -> Stopped | None:
    """Halt the step's latest pass as :func:`stop` does when it is ``claim_id``'s — a run of
    it ran under the claim, or it has no run yet, a pass begun at its gate under the claim
    holding the step: what the step leaving that claim owes the pass (``ownership``), since
    a gate answered afterwards would otherwise launch the next stage as nobody's. The caller
    holds the step's launch lock when it is free. The plan is not read: its facts only tell
    a pass complete when the step reads done, and one halted then starts nothing either way.
    Nothing is waited for — a supervisor here obeys its fence within a second."""
    entries = _latest_entries(project_dir, step_id)
    runs = [e for e in entries if isinstance(e, LedgerRecord)]
    if runs and not any(r.claim == claim_id for r in runs):
        return None
    return _halt(project_dir, step_id, entries, Facts(), by, why, 0.0)


def _halt(
    project_dir: Path,
    step_id: str,
    entries: Sequence[passes.Entry],
    facts: Facts,
    by: str,
    why: str,
    wait: float,
) -> Stopped | None:
    if not _left(project_dir, step_id, facts, entries):
        return None
    runs = [e for e in entries if isinstance(e, LedgerRecord)]
    latest = entries[-1]
    targets = [r for r in runs if not r.over or (r is latest and not r.fence)]
    asked = [e for e in entries if isinstance(e, Question) and not e.settled]
    for question in asked:
        questions.update(
            project_dir,
            question.id,
            lambda q: q if q.settled else questions.withdrawn(q, why, now_stamp()),
        )
    still = supervisor.stop_and_wait(project_dir, targets, by, why, wait)
    here = ledger.machine_id()
    return Stopped(
        latest.pass_,
        tuple(f"{r.stage} attempt {r.attempt} was {_run_state(r)}" for r in targets),
        tuple(q.short for q in asked),
        tuple(still),
        any(r.machine != here for r in targets),
    )


def _run_state(run: LedgerRecord) -> str:
    if run.over:
        return "done, its next stage not yet begun"
    if run.last_turn is None:
        return "not started"
    return "parked" if run.parked else "running"


def _under_way(next_: Next) -> str:
    if isinstance(next_, Wait):
        return next_.why
    stage = next_.stage if isinstance(next_, Launch | Ask | Progress) else ""
    return f"its {stage} stage is due — `dplanner playbook advance` moves it on"


def _orphan(pass_: _Pass, step: Step) -> LedgerRecord | None:
    """The pass's first run, when that is all the pass is and it never began: no turn, no
    supervisor, its step not as its launch leaves it (:func:`supervisor.launch_stands`). Its
    launch died between writing it and saving its claim — the start only ever follows the
    claim — so nothing will run it: what ``revive`` deletes once it is old enough, and a new
    launch at once."""
    (first, *rest) = pass_.entries
    if rest or not isinstance(first, LedgerRecord) or first.turns or first.over:
        return None
    if supervisor.launch_stands(first, step) or supervisor.supervised(ledger.run_dir(first.run)):
        return None
    return first


def _lapsed(project_dir: Path, pass_: _Pass) -> bool:
    """Answer for the clock a held launch whose reset has passed — what :func:`wake` does,
    for a pass whose waker died with its machine. True when it answered one."""
    last = pass_.entries[-1] if pass_.entries else None
    if not isinstance(last, Question) or last.kind != questions.LIMIT or last.settled:
        return False
    reset = limits.parse(last.resets)
    if reset is None or reset > datetime.now(UTC):
        return False
    questions.clock_answer(project_dir, last.id)
    return True


def wake(
    project_dir: Path,
    question_id: str,
    *,
    library: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    grace: float = 60.0,
) -> str:
    """Wait for a held launch's reset, answer its card for the clock, and advance its pass —
    ``playbook wake``, started detached when the card is written (``supervisor.wake_detached``).
    A clock is no person: it waits on a time, never on anybody, and stops as soon as the card
    is answered or gone."""
    while True:
        question = questions.find(project_dir, question_id)
        if question is None or question.state not in (questions.OPEN, questions.ESCALATED):
            return f"{questions.short(question_id)} no longer waits for the clock"
        reset = limits.parse(question.resets)
        left = 0.0 if reset is None else (reset - datetime.now(UTC)).total_seconds() + grace
        if left <= 0:
            questions.clock_answer(project_dir, question_id)
            supervisor.advance_detached(question.step, library=library)
            return f"{question.short}: the limit has reset; its pass advances"
        sleep(min(left, 60.0))


def _latest_pass(project_dir: Path, step_id: str) -> "_Pass | str":
    """The step's latest pass as its records say, or why there is none to advance."""
    return _pass_of(step_id, ledger.records(project_dir), questions.records(project_dir))


def _latest_entries(project_dir: Path, step_id: str) -> list[passes.Entry]:
    """The step's latest pass's runs and questions, oldest first, by pass id alone."""
    return _entries_of(step_id, ledger.records(project_dir), questions.records(project_dir))


def _entries_of(
    step_id: str, records: Sequence[LedgerRecord], asked_all: Sequence[Question]
) -> list[passes.Entry]:
    runs = [r for r in records if r.step == step_id and r.pass_]
    asked = [q for q in asked_all if q.step == step_id and q.pass_]
    entries = passes.in_order(runs, asked)
    return [e for e in entries if e.pass_ == entries[-1].pass_] if entries else []


def _pass_of(
    step_id: str, records: Sequence[LedgerRecord], asked_all: Sequence[Question]
) -> "_Pass | str":
    """:func:`_latest_pass` over records already read: a project's, for every step at once."""
    entries = _entries_of(step_id, records, asked_all)
    if not entries:
        return "no playbook pass to advance"
    pass_id = entries[-1].pass_
    first = entries[0]
    settings = passes.Settings.from_json(first.settings or {})
    if settings is None:
        return f"pass {pass_id} has lost its first record, and with it its settings"
    playbook = preset(settings.preset)
    if playbook is None or playbook.revision != settings.revision:
        return (
            f"pass {pass_id} runs {settings.preset} revision {settings.revision},"
            " which this build does not have"
        )
    runs_of = [e for e in entries if isinstance(e, LedgerRecord)]
    machine = (
        runs_of[0].machine
        if runs_of
        else first.by.get("machine", "")
        if isinstance(first, Question)
        else ""
    )
    directory = next((r.directory for r in runs_of if r.directory), "")
    member, claim = (runs_of[0].callsign, runs_of[0].claim) if runs_of else ("", "")
    return _Pass(pass_id, playbook, settings, entries, directory, machine, member, claim)


# -- where each pass stands -----------------------------------------------------------------------

# How long a pass that ended keeps its strip: one that ended overnight is still there in the
# morning, and the step's next pass replaces it sooner.
ENDED_SHOWN = timedelta(hours=24)


def standing_of(project_dir: Path, step: Step, now: datetime) -> Standing | None:
    """Where the step's latest pass stands, however long ago it ended — ``playbook show``."""
    return _standing(step, ledger.records(project_dir), questions.records(project_dir), now)


def standings(project_dir: Path, steps: Sequence[Step], now: datetime) -> dict[str, Standing]:
    """Where every pass under way among ``steps`` stands, and every pass that ended within
    :data:`ENDED_SHOWN` — the card's strip. The project's records are read once."""
    records, asked = ledger.records(project_dir), questions.records(project_dir)
    found = {}
    for step in steps:
        stands = _standing(step, records, asked, now)
        if stands is not None and not (stands.ended and _age(stands.at, now) > ENDED_SHOWN):
            found[step.id] = stands
    return found


def _standing(
    step: Step, records: Sequence[LedgerRecord], asked: Sequence[Question], now: datetime
) -> Standing | None:
    pass_ = _pass_of(step.id, records, asked)
    if isinstance(pass_, str) or _orphan(pass_, step):
        return None
    runs = {e.run for e in pass_.entries if isinstance(e, LedgerRecord)}
    parks = [q for q in asked if q.run and q.run in runs]
    return passes.standing(pass_.playbook, pass_.settings, pass_.entries, parks, _facts(step), now)


def _age(stamp: str, now: datetime) -> timedelta:
    moment = limits.parse(stamp)
    return now - moment if moment is not None else timedelta.max
