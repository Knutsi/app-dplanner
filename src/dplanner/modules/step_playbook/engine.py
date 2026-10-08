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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from dplanner.cli import CliContext, CliError
from dplanner.domain import ledger, questions
from dplanner.domain.headless import StageKind
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.model import Step
from dplanner.domain.questions import Question
from dplanner.modules.agent_briefing.prompt import PromptPart
from dplanner.modules.agent_briefing.stages import approved_part, findings_part, review_part
from dplanner.modules.agent_supervisor import supervisor
from dplanner.modules.step_playbook import passes
from dplanner.modules.step_playbook.aspect import read, resolve
from dplanner.modules.step_playbook.passes import (
    GATE,
    GATE_OPTIONS,
    Ask,
    Complete,
    Facts,
    Halted,
    Launch,
    Next,
    Progress,
    Settings,
    Wait,
)
from dplanner.modules.step_playbook.presets import Playbook, preset
from dplanner.modules.step_playbook.workflows import approved
from dplanner.planning.status import Status, stored


class StageLauncher(Protocol):
    """What the engine needs of the launch: who can run here, and a stage's run started."""

    def runnable(self) -> tuple[str, ...]:
        """The harnesses some launch profile runs headless: what a role may name."""
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
    ) -> str:
        """Write the stage's run and start its supervisor; its id. Raises ``CliError``."""
        ...


# `progress`: merge the step's PR into its feature branch and accept it — "" when it was
# accepted, else why not (the mainline, no PR, a merge gh refused).
Accept = Callable[[CliContext, Step], str]


@dataclass(frozen=True)
class Planned:
    """A pass about to begin: checked, its settings pinned, nothing written."""

    pass_: str
    playbook: Playbook
    settings: Settings


@dataclass(frozen=True)
class Engine:
    launch: StageLauncher
    accept: Accept

    def plan(self, context: CliContext, step: Step, chosen: str, implementer: str) -> Planned:
        """A new pass of ``chosen`` (or the step's own playbook) on ``step``, the work stages
        run by ``implementer``'s harness — or ``CliError`` saying why it cannot begin."""
        project = context.library.project_of(step.id)
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
        return Planned(ledger.new_run_id(), playbook, settings)

    def start(
        self, context: CliContext, step: Step, chosen: str, implementer: str
    ) -> Callable[[str], str]:
        """``agent run --playbook``'s half: :meth:`plan` now, and :meth:`begin` — handed the
        worktree — once the launch has saved its claim."""
        planned = self.plan(context, step, chosen, implementer)
        return lambda directory: self.begin(context, step, planned, directory)

    def begin(self, context: CliContext, step: Step, planned: Planned, directory: str) -> str:
        """Act the pass's first stage. The caller holds the step's launch lock and has
        saved its claim; ``directory`` is the worktree it placed."""
        pass_ = _Pass(planned.pass_, planned.playbook, planned.settings, [], directory)
        return self._act(context, step, pass_, _facts(step))

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
            return self._act(context, step, pass_, _facts(step))

    # -- acting -----------------------------------------------------------------------------

    def _act(self, context: CliContext, step: Step, pass_: "_Pass", facts: Facts) -> str:
        next_ = passes.due(pass_.playbook, pass_.settings, pass_.entries, facts)
        said = self._do(context, step, pass_, next_)
        if not isinstance(next_, Wait):
            _settle_answers(context, step, pass_)
        return f"{step.title}: {said}"

    def _do(self, context: CliContext, step: Step, pass_: "_Pass", next_: Next) -> str:
        match next_:
            case Wait(why) | Halted(why):
                return why
            case Complete(why, set_done):
                if set_done:
                    change = approved(step, today=context.clock.today())
                    if change.command is not None:
                        context.apply(change.command)
                        return f"{why} — the step is done"
                return why
            case Launch():
                run = self.launch(
                    context,
                    step,
                    kind=next_.kind,
                    harness=next_.harness,
                    extra=_parts(next_),
                    dress=pass_.dress(next_),
                    findings=[f["ref"] for f in next_.findings if "ref" in f],
                    directory=pass_.directory,
                )
                return f"{next_.stage} (attempt {next_.attempt}) launched as run {run}"
            case Ask():
                return _ask(context, step, pass_, next_)
            case Progress(stage):
                why = self.accept(context, step)
                if not why:
                    return "accepted on its branch"
                attempt = 1 + sum(
                    1 for e in pass_.entries if isinstance(e, Question) and e.stage == stage
                )
                return _ask(
                    context,
                    step,
                    pass_,
                    Ask(
                        stage,
                        attempt,
                        GATE,
                        questions.DECISION,
                        f"Progress could not accept the work: {why}. Does it pass?",
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


def _ask(context: CliContext, step: Step, pass_: _Pass, ask: Ask) -> str:
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
    )
    questions.write(project_dir, question)
    return f"{ask.stage} asks {question.short} ({ask.purpose})"


def _settle_answers(context: CliContext, step: Step, pass_: _Pass) -> None:
    """Mark consumed every answer of the pass that has been acted on — after the act, so a
    crash between leaves an answer to act on again, never one lost."""
    project_dir = context.store.project_dir(context.library.project_of(step.id).id)
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


def _latest_pass(project_dir: Path, step_id: str) -> "_Pass | str":
    """The step's latest pass as its records say, or why there is none to advance."""
    runs = [r for r in ledger.records(project_dir) if r.step == step_id and r.pass_]
    asked = [q for q in questions.records(project_dir) if q.step == step_id and q.pass_]
    entries = passes.in_order(runs, asked)
    if not entries:
        return "no playbook pass to advance"
    pass_id = entries[-1].pass_
    entries = [e for e in entries if e.pass_ == pass_id]
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
    return _Pass(pass_id, playbook, settings, entries, directory, machine)
