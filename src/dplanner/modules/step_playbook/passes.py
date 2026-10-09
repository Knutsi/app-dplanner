"""Where a playbook's pass stands, and what is due next — derived, never stored.

A **pass** is one run of a playbook on a step. It keeps no record of its own: its runs (one per
agent stage attempt, ``domain/ledger.py``) and its gate questions (``domain/questions.py``) all
carry its id, and :func:`due` reads them, oldest first, to say what the engine does next —
launch a stage, ask a gate, accept the work on its branch, or nothing. Reading rather than
remembering is what lets any process advance a pass, any number of times, and launch a stage
once: the record a launch writes before its process starts is what the next reading finds.

The rules are ``docs/architecture/playbooks.md``'s:

- the stages run in their list's order; a gate's *changes* goes back to the nearest earlier
  ``plan`` or ``execute``, or to a ``fix`` of the implementer when there is none, and the
  stages after it run again — except a gate that already passed in the pass, which stands;
- a gate gives at most ``rounds`` verdicts in a pass; *changes* on the last is a ``round-cap``
  question, and only its answer buys another round;
- a failure is never a verdict: a run that did not end ``done`` stops the pass where it is,
  and a review done without a verdict is an ``escalation``, not a pass;
- a work stage resumes the implementer's latest session in the pass; a review never does.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from dplanner.domain import ledger, questions
from dplanner.domain.headless import StageKind, TurnEnd, stage_kind, verdict_of
from dplanner.domain.ledger import LedgerRecord
from dplanner.domain.questions import Question
from dplanner.modules.agent_briefing.stages import numbered
from dplanner.modules.agent_supervisor import limits
from dplanner.modules.step_playbook.aspect import Choice
from dplanner.modules.step_playbook.presets import ROUNDS, Playbook, StageRole

FIX = "fix"  # The work stage a playbook with no work before its gate is sent back to.
GATE, ROUND_CAP, ESCALATION = "gate", "round-cap", "escalation"

# The answers a pass's questions offer: (label, what it means).
PASS, CHANGES, STOP = "Pass", "Changes", "Stop"
ACCEPT, ONE_MORE, TAKE_OVER, RETRY = "Accept as is", "One more round", "Take over", "Retry"
GATE_OPTIONS = (
    (PASS, "The work is good enough: the playbook goes on"),
    (CHANGES, "Send it back — answer with what must change, in your own words"),
    (STOP, "End the pass here"),
)
ROUND_CAP_OPTIONS = (
    (ACCEPT, "Go on as if the gate passed"),
    (ONE_MORE, "One more round of fix and verdict"),
    (TAKE_OVER, "A person takes the step from here; the pass ends"),
    (STOP, "End the pass here"),
)
ESCALATION_OPTIONS = (
    (RETRY, "Run the stage again"),
    (ACCEPT, "Go on as if it passed"),
    (STOP, "End the pass here"),
)

Entry = LedgerRecord | Question


@dataclass(frozen=True)
class Settings:
    """What a pass pinned when it began: an edit of the step's choice applies to the next
    pass, never to one under way (*A pass pins its settings*)."""

    preset: str
    revision: int
    rounds: int
    implementer: str  # The harness of the work stages.
    reviewer: str  # The harness of an "other agent" review; the implementer's when alone.
    overrides: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "revision": self.revision,
            "rounds": float(self.rounds),  # A number on disk is a float (FORMAT.md).
            "roles": {"implementer": self.implementer, "reviewer": self.reviewer},
            "overrides": dict(self.overrides),
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any] | None) -> "Settings | None":
        if not raw or not isinstance(raw.get("preset"), str):
            return None
        given = raw.get("roles")
        roles: Mapping[str, Any] = given if isinstance(given, dict) else {}
        rounds, revision = raw.get("rounds"), raw.get("revision")
        overrides = raw.get("overrides")
        return cls(
            preset=raw["preset"],
            revision=int(revision) if isinstance(revision, int | float) else 0,
            rounds=int(rounds) if isinstance(rounds, int | float) and rounds >= 1 else ROUNDS,
            implementer=str(roles.get("implementer", "")),
            reviewer=str(roles.get("reviewer", "")),
            overrides=dict(overrides) if isinstance(overrides, dict) else {},
        )


def pinned(
    playbook: Playbook, choice: Choice | None, implementer: str, runnable: Sequence[str]
) -> Settings:
    """The settings a new pass of ``playbook`` pins: the step's own overrides, the
    implementer's harness, and the reviewer — the step's, else another vendor's that some
    profile runs headless here, else the implementer's own in a fresh session. Raises
    ``ValueError`` for a role no profile runs: it is refused, never swapped."""
    if implementer not in runnable:
        raise ValueError(f"no launch profile runs {implementer} headless")
    overrides: dict[str, Any] = {}
    if choice is not None and choice.rounds is not None:
        overrides["rounds"] = float(choice.rounds)
    if choice is not None and choice.reviewer is not None:
        overrides["reviewer"] = choice.reviewer
    reviewer = overrides.get("reviewer") or next(
        (harness for harness in runnable if harness != implementer), implementer
    )
    if reviewer not in runnable and playbook.reviews_with_other():
        raise ValueError(f"no launch profile runs the reviewer, {reviewer}, headless")
    return Settings(
        preset=playbook.id,
        revision=playbook.revision,
        rounds=choice.rounds if choice is not None and choice.rounds is not None else ROUNDS,
        implementer=implementer,
        reviewer=reviewer,
        overrides=overrides,
    )


def agents_of(playbook: Playbook, settings: Settings) -> tuple[str, ...]:
    """The harnesses a pass of ``playbook`` under ``settings`` runs: the implementer's, which
    does the work and any fix, and the reviewer's where a review is another agent's."""
    other = (settings.reviewer,) if playbook.reviews_with_other() else ()
    return tuple(dict.fromkeys((settings.implementer, *other)))


# -- what is due --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Launch:
    """An agent stage's next attempt: a new run."""

    stage: str  # Its id in the playbook, or FIX.
    kind: StageKind
    harness: str
    attempt: int
    resume: LedgerRecord | None = None  # The run whose session a work stage continues.
    plan: LedgerRecord | None = None  # The approved plan an execute follows.
    findings: tuple[Mapping[str, Any], ...] = ()  # What a loop-back acts on, each with a ref.
    history: tuple[Mapping[str, Any], ...] = ()  # A review's earlier rounds and declines.


@dataclass(frozen=True)
class Ask:
    """A question of the pass's own: a gate, a round cap, an escalation."""

    stage: str
    attempt: int
    purpose: str
    kind: str
    text: str
    options: tuple[tuple[str, str], ...]
    body: str = ""
    plan: LedgerRecord | None = None  # A plan-approval's plan, which becomes its body.
    resets: str = ""  # For a held launch's card: when the account comes back.


@dataclass(frozen=True)
class Progress:
    """Accept the step's work on its feature branch: DPlanner's own act."""

    stage: str


@dataclass(frozen=True)
class Complete:
    why: str
    set_done: bool = False  # A playbook with nothing to merge: its approval is the step done.


@dataclass(frozen=True)
class Wait:
    why: str


@dataclass(frozen=True)
class Halted:
    why: str


Next = Launch | Ask | Progress | Complete | Wait | Halted


@dataclass(frozen=True)
class Facts:
    """What the plan says about the step, beside the pass's records."""

    done: bool = False  # The step reads done: whatever the pass had left is moot.
    at_review: bool = False  # It reads Ready for review: a new pass starts at its first gate.


def in_order(runs: Sequence[LedgerRecord], asked: Sequence[Question]) -> list[Entry]:
    """A pass's runs and questions, oldest first: the order they were made in."""
    entries: list[Entry] = [*runs, *asked]
    return sorted(
        entries, key=lambda e: (_stamp(e), e.run if isinstance(e, LedgerRecord) else e.id)
    )


def due(playbook: Playbook, settings: Settings, entries: Sequence[Entry], facts: Facts) -> Next:
    """What the pass needs next, from its records oldest first (:func:`in_order`)."""
    return _Reading(playbook, settings, list(entries)).due(facts)


# What a pass asks when it could not act: an account held, or a launch or a merge refused.
REFUSED = (questions.LIMIT, questions.BLOCKED)
REFUSED_OPTIONS = (
    (questions.RETRY_NOW, "Try again now"),
    (STOP, "End the pass here"),
)


def retried(question: Question) -> bool:
    """Whether a refusal the pass asked about was answered *Retry now*, or by the clock."""
    by = question.answer.get("by", {})
    return (
        question.purpose == ESCALATION
        and question.kind in REFUSED
        and question.state in (questions.ANSWERED, questions.CONSUMED)
        and (
            (isinstance(by, dict) and by.get("kind") == questions.CLOCK)
            or _is(answer_word(question), questions.RETRY_NOW)
        )
    )


def answer_word(question: Question) -> str:
    """The answer given, as one text: the chosen label, or the words."""
    given = question.answer.get("answers", {})
    return str(next(iter(given.values()), "")).strip() if isinstance(given, dict) else ""


def _verdict(run: LedgerRecord) -> Mapping[str, Any]:
    """The run's verdict when it is one (``headless.verdict_of``), else nothing at all."""
    return verdict_of(run.verdict) or {}


def _stamp(entry: Entry) -> str:
    return entry.launched if isinstance(entry, LedgerRecord) else entry.asked


def _is(word: str, *labels: str) -> bool:
    """Whether an answer is one of these choices, exactly — case, spacing and a closing stop
    aside. Anything more is words: "Pass only after fixing X" is not *Pass*."""
    said = " ".join(word.casefold().split()).rstrip(".!")
    return any(said == label.casefold() for label in labels)


@dataclass
class _Reading:
    playbook: Playbook
    settings: Settings
    entries: list[Entry]
    ids: tuple[str, ...] = field(init=False)
    roles: dict[str, StageRole] = field(init=False)

    def __post_init__(self) -> None:
        self.ids = self.playbook.stage_ids()
        self.roles = dict(zip(self.ids, (s.role for s in self.playbook.stages), strict=True))

    # -- the latest record --------------------------------------------------------------------

    def due(self, facts: Facts) -> Next:
        if not self.entries:
            gates = [i for i, stage in enumerate(self.playbook.stages) if stage.role.is_gate]
            return self._enter(gates[0] if facts.at_review and gates else 0)
        last = self.entries[-1]
        if isinstance(last, LedgerRecord):
            if not last.over:
                return Wait(f"run {last.run} is {'parked' if last.parked else 'running'}")
            if last.fence:
                return Halted(f"run {last.run} was stopped: {last.fence.get('why', '')}")
            end = last.last_turn.end if last.last_turn is not None else ""
            if end != TurnEnd.DONE:
                return Halted(f"run {last.run} ended {end or 'without a turn'}")
        elif last.state in (questions.OPEN, questions.ESCALATED):
            return Wait(f"{last.short} waits for an answer")
        elif retried(last):
            # A launch or a merge the pass could not make: on its retry, what was due is.
            return _Reading(self.playbook, self.settings, self.entries[:-1]).due(facts)
        elif last.state == questions.WITHDRAWN:
            return Halted(f"{last.short} was withdrawn")
        if facts.done:
            return Complete("the step is done")
        return self._after_run(last) if isinstance(last, LedgerRecord) else self._answered(last)

    def _after_run(self, run: LedgerRecord) -> Next:
        if stage_kind(run.stage) is not StageKind.REVIEW:
            return self._after(run.stage)
        outcome = _verdict(run).get("outcome")
        if outcome == "pass":
            return self._after(run.stage)
        if outcome == "changes":
            findings = _verdict(run).get("findings")
            listed = findings if isinstance(findings, list) else []
            return self._changes(
                run.stage,
                tuple(
                    {**finding, "ref": {"run": run.run, "index": index}}
                    for index, finding in enumerate(listed)
                    if isinstance(finding, dict)
                ),
            )
        return Ask(
            run.stage,
            self._asked(run.stage, ESCALATION) + 1,
            ESCALATION,
            questions.DECISION,
            f"The {run.stage} stage ended without a verdict, even when asked for one. How"
            " should the pass go on?",
            ESCALATION_OPTIONS,
        )

    def _answered(self, question: Question) -> Next:
        word, stage = answer_word(question), question.stage
        if question.purpose == GATE:
            if _is(word, PASS):
                return self._after(stage)
            if _is(word, STOP):
                return Halted(f"{question.short} stopped the pass")
            return self._changes(stage, (_note(question),))
        if _is(word, ACCEPT):
            return self._after(stage)
        if question.purpose == ROUND_CAP and _is(word, ONE_MORE):
            return self._loop_back(stage, self._open_findings(stage))
        if question.purpose == ESCALATION and _is(word, RETRY):
            return self._enter(self.ids.index(stage))
        return Halted(f"{question.short} was answered {word or 'with nothing'}")

    # -- moving through the list --------------------------------------------------------------

    def _after(self, stage: str) -> Next:
        """The stage after ``stage`` that is still to run; a fix is before every stage."""
        start = self.ids.index(stage) + 1 if stage in self.ids else 0
        for index in range(start, len(self.ids)):
            if not (self.roles[self.ids[index]].is_gate and self._passed(self.ids[index])):
                return self._enter(index)
        produced = any(r in (StageRole.EXECUTE, StageRole.REVIEW) for r in self.roles.values())
        return Complete(f"{self.playbook.name} is through", set_done=not produced)

    def _enter(self, index: int) -> Next:
        stage, role = self.ids[index], self.playbook.stages[index].role
        if role in (StageRole.PLAN, StageRole.EXECUTE):
            plan = self._latest(StageRole.PLAN.value) if role is StageRole.EXECUTE else None
            return Launch(
                stage,
                StageKind.PLAN if role is StageRole.PLAN else StageKind.EXECUTE,
                self.settings.implementer,
                self._runs(stage) + 1,
                resume=self._work_session(),
                plan=plan if plan is not None and not self._runs(stage) else None,
            )
        if role is StageRole.REVIEW:
            other = self.playbook.stages[index].reviewer == "other"
            return Launch(
                stage,
                StageKind.REVIEW,
                self.settings.reviewer if other else self.settings.implementer,
                self._runs(stage) + 1,
                history=self._history(stage),
            )
        if role is StageRole.PROGRESS:
            return Progress(stage)
        after_plan = index > 0 and self.playbook.stages[index - 1].role is StageRole.PLAN
        return Ask(
            stage,
            self._asked(stage, GATE) + 1,
            GATE,
            questions.PLAN_APPROVAL if after_plan else questions.DECISION,
            "Approve the plan, or send it back with what must change?"
            if after_plan
            else "Does the work pass, or what must change?",
            GATE_OPTIONS,
            plan=self._latest(StageRole.PLAN.value) if after_plan else None,
        )

    def _changes(self, gate: str, findings: tuple[Mapping[str, Any], ...]) -> Next:
        """A gate asked for changes: back to the work, unless it has given its last verdict."""
        if self._verdicts(gate) < self._cap(gate):
            return self._loop_back(gate, findings)
        declined = self._declines()
        listed = [{**f, "declined": declined.get(_ref(f), "")} for f in findings]
        return Ask(
            gate,
            self._asked(gate, ROUND_CAP) + 1,
            ROUND_CAP,
            questions.DECISION,
            f"The {gate} gate still asks for changes after its last round"
            f" ({self._verdicts(gate)} of {self._cap(gate)}). What now?",
            ROUND_CAP_OPTIONS,
            body=numbered(listed),
        )

    def _loop_back(self, gate: str, findings: tuple[Mapping[str, Any], ...]) -> Next:
        index = self.ids.index(gate) if gate in self.ids else len(self.ids)
        earlier = [
            i
            for i in range(index)
            if self.playbook.stages[i].role in (StageRole.PLAN, StageRole.EXECUTE)
        ]
        stage = self.ids[earlier[-1]] if earlier else FIX
        planning = bool(earlier) and self.playbook.stages[earlier[-1]].role is StageRole.PLAN
        return Launch(
            stage,
            StageKind.PLAN if planning else StageKind.EXECUTE,
            self.settings.implementer,
            self._runs(stage) + 1,
            resume=self._work_session(),
            findings=findings,
        )

    # -- reading the records ------------------------------------------------------------------

    def _run_list(self, stage: str | None = None) -> list[LedgerRecord]:
        return [
            e
            for e in self.entries
            if isinstance(e, LedgerRecord) and (stage is None or e.stage == stage)
        ]

    def _runs(self, stage: str) -> int:
        return len(self._run_list(stage))

    def _latest(self, stage: str) -> LedgerRecord | None:
        done = [r for r in self._run_list(stage) if r.over and not r.fence]
        return done[-1] if done else None

    def _work_session(self) -> LedgerRecord | None:
        """The implementer's latest session in the pass, which a work stage continues."""
        work = [
            r
            for r in self._run_list()
            if stage_kind(r.stage) is not StageKind.REVIEW
            and r.session
            and r.harness == self.settings.implementer
        ]
        return work[-1] if work else None

    def _questions(self, stage: str, purpose: str) -> list[Question]:
        return [
            e
            for e in self.entries
            if isinstance(e, Question) and e.stage == stage and e.purpose == purpose
        ]

    def _asked(self, stage: str, purpose: str) -> int:
        return len(self._questions(stage, purpose))

    def _settled_answers(self, stage: str, purpose: str) -> list[str]:
        return [
            answer_word(q)
            for q in self._questions(stage, purpose)
            if q.state in (questions.ANSWERED, questions.CONSUMED)
        ]

    def _verdicts(self, gate: str) -> int:
        """The verdicts the gate gave in the pass — rounds spent; a failure spent none."""
        given = sum(
            1 for r in self._run_list(gate) if _verdict(r).get("outcome") in ("pass", "changes")
        )
        return given + sum(1 for word in self._settled_answers(gate, GATE) if not _is(word, STOP))

    def _cap(self, gate: str) -> int:
        more = sum(1 for word in self._settled_answers(gate, ROUND_CAP) if _is(word, ONE_MORE))
        return self.settings.rounds + more

    def _passed(self, gate: str) -> bool:
        if any(_verdict(r).get("outcome") == "pass" for r in self._run_list(gate)):
            return True
        return any(_is(w, PASS) for w in self._settled_answers(gate, GATE)) or any(
            _is(w, ACCEPT)
            for purpose in (ROUND_CAP, ESCALATION)
            for w in self._settled_answers(gate, purpose)
        )

    def _declines(self) -> dict[tuple[str, str, int], str]:
        """Every finding the implementer declined in the pass, by its reference: its reason."""
        found: dict[tuple[str, str, int], str] = {}
        for run in self._run_list():
            for each in run.declined:
                ref = each.get("finding")
                if isinstance(ref, dict):
                    found[_ref({"ref": ref})] = str(each.get("reason", ""))
        return found

    def _open_findings(self, gate: str) -> tuple[Mapping[str, Any], ...]:
        """The gate's latest findings — its last review's, or the note its last answer of
        *changes* gave: what one more round acts on."""
        for entry in reversed(self.entries):
            if entry.stage != gate:
                continue
            if isinstance(entry, LedgerRecord) and _verdict(entry).get("outcome") == "changes":
                listed = _verdict(entry).get("findings")
                return tuple(
                    {**f, "ref": {"run": entry.run, "index": i}}
                    for i, f in enumerate(listed if isinstance(listed, list) else [])
                    if isinstance(f, dict)
                )
            if isinstance(entry, Question) and entry.purpose == GATE:
                word = answer_word(entry)
                if entry.state in (questions.ANSWERED, questions.CONSUMED) and not _is(
                    word, PASS, STOP
                ):
                    return (_note(entry),)
        return ()

    def _history(self, gate: str) -> tuple[Mapping[str, Any], ...]:
        """What the gate found in earlier rounds, with the implementer's reason where it
        declined a finding — what the next round reads."""
        declined = self._declines()
        found = []
        for run in self._run_list(gate):
            listed = _verdict(run).get("findings")
            for index, finding in enumerate(listed if isinstance(listed, list) else []):
                if isinstance(finding, dict):
                    ref = {"run": run.run, "index": index}
                    found.append({**finding, "declined": declined.get(_ref({"ref": ref}), "")})
        return tuple(found)


def _note(question: Question) -> Mapping[str, Any]:
    """A gate's answer of *changes* as the finding it is: its words, by its question."""
    word = answer_word(question)
    said = word.split(":", 1)[1].strip() if word.casefold().startswith("changes:") else word
    text = "" if _is(said, CHANGES) else said
    return {
        "text": text or "Changes were asked for, with no note",
        "ref": {"question": question.id, "index": 0},
    }


def _ref(finding: Mapping[str, Any]) -> tuple[str, str, int]:
    ref = finding.get("ref")
    if not isinstance(ref, dict):
        return ("", "", 0)
    kind = "run" if "run" in ref else "question"
    index = ref.get("index")
    return (kind, str(ref.get(kind, "")), index if isinstance(index, int) else 0)


# -- where a pass stands, in words --------------------------------------------------------------


@dataclass(frozen=True)
class Standing:
    """Where a pass stands, in a person's words: what the card's playbook strip and ``playbook
    show`` both say. Derived from the pass's records every time, never stored."""

    pass_id: str
    playbook: str  # The playbook's name.
    phrase: str  # "Review 1/2", "Waits for you · plan approval", "Parked until 14:20".
    tone: str  # "" quiet | "busy" | "warn" | "good" | "bad": ``theme/tones``' words.
    stages: tuple[str, ...]  # The playbook's stage labels, in order.
    current: int  # The stage the pass stands at, by index; -1 for none.
    ended: bool  # Done or stopped: nothing more is due, not even a person's merge.
    at: str  # The stamp of the pass's latest record.


def standing(
    playbook: Playbook,
    settings: Settings,
    entries: Sequence[Entry],
    parks: Sequence[Question],
    facts: Facts,
    now: datetime,
) -> Standing:
    """Where the pass stands, from its records oldest first and the questions its runs parked
    on (``parks``: a run's own question carries its run, not the pass). ``now`` says whether a
    usage hold's reset is today."""
    reading = _Reading(playbook, settings, list(entries))
    next_ = reading.due(facts)
    last = entries[-1] if entries else None
    phrase, tone, stage = _words(reading, next_, last, parks, facts, now)
    return Standing(
        pass_id=last.pass_ if last is not None else "",
        playbook=playbook.name,
        phrase=phrase,
        tone=tone,
        stages=tuple(stage.label for stage in playbook.stages),
        current=reading.ids.index(stage) if stage in reading.ids else -1,
        ended=isinstance(next_, Halted) or phrase == DONE,
        at=_stamp(last) if last is not None else "",
    )


def describe(standing: Standing) -> str:
    """The stages of the pass with the one it stands at marked, under its phrase — the card's
    tooltip and ``playbook show``'s lines alike."""
    lines = [f"{standing.phrase} · {standing.playbook} (pass {standing.pass_id})"]
    lines += [
        f"{'▸' if index == standing.current else ' '} {label}"
        for index, label in enumerate(standing.stages)
    ]
    return "\n".join(lines)


DONE = "Done"
TAKEN_OVER = "Taken over"


def _words(
    reading: _Reading,
    next_: Next,
    last: Entry | None,
    parks: Sequence[Question],
    facts: Facts,
    now: datetime,
) -> tuple[str, str, str]:
    """(phrase, tone, stage id) for what is due, read against the latest record."""
    if isinstance(next_, Complete):
        # A pass that produced work never merges it into the mainline: until somebody does
        # and the step reads done, the work is not done, however through the pass is.
        if facts.done or next_.set_done:
            return DONE, "good", ""
        return "Waits for merge", "warn", ""
    if isinstance(next_, Halted):
        stage = last.stage if last is not None else ""
        return (TAKEN_OVER, "", stage) if _taken_over(reading, last) else ("Stopped", "bad", stage)
    if isinstance(next_, Progress):
        return "Merging", "busy", next_.stage
    if isinstance(next_, Launch):
        return _working(reading, next_.stage, next_.attempt), "busy", next_.stage
    if isinstance(next_, Ask):
        return _waiting(next_.kind, next_.purpose, next_.stage), "warn", next_.stage
    if isinstance(last, LedgerRecord):
        turn = last.last_turn
        if not last.parked or turn is None:
            return _working(reading, last.stage, last.attempt), "busy", last.stage
        held = limits.parse(turn.resets) if turn.end == TurnEnd.LIMIT else None
        if held is not None:
            return f"Parked until {limits.clock(held, now)}", "", last.stage
        asked = next((q for q in parks if q.id == turn.question), None)
        phrase, tone = _asked(asked, now) if asked is not None else (_waiting("", "", ""), "warn")
        return phrase, tone, last.stage
    if isinstance(last, Question):
        return (*_asked(last, now), last.stage)
    return "", "", ""


def _taken_over(reading: _Reading, last: Entry | None) -> bool:
    """A halted pass a person took from here: its latest run fenced by *Open Session*, or a
    round cap answered *Take over*."""
    runs = [entry for entry in reading.entries if isinstance(entry, LedgerRecord)]
    fence = runs[-1].fence if runs else None
    if fence is not None and fence.get("why") == ledger.TAKEN_OVER:
        return True
    return (
        isinstance(last, Question)
        and last.purpose == ROUND_CAP
        and _is(answer_word(last), TAKE_OVER)
    )


def _working(reading: _Reading, stage: str, attempt: int) -> str:
    """A stage at work. A work stage's later attempts are the loop-backs a gate sent it."""
    kind = stage_kind(stage)
    if kind is StageKind.REVIEW:
        cap = reading._cap(stage)
        return f"Review {min(reading._verdicts(stage) + 1, cap)}/{cap}"
    if stage == FIX:
        return f"Fixing (round {attempt})"
    if kind is StageKind.PLAN:
        return "Planning" if attempt <= 1 else f"Replanning (round {attempt - 1})"
    return "Executing" if attempt <= 1 else f"Fixing (round {attempt - 1})"


def _asked(question: Question, now: datetime) -> tuple[str, str]:
    held = limits.parse(question.resets) if question.kind == questions.LIMIT else None
    if question.state == questions.ESCALATED:
        return "Escalated", "warn"
    if held is not None:
        return f"Parked until {limits.clock(held, now)}", ""
    return _waiting(question.kind, question.purpose, question.stage), "warn"


def _waiting(kind: str, purpose: str, stage: str) -> str:
    what = "round cap" if purpose == ROUND_CAP else questions.waits_for(kind)
    # A stage id is its role, numbered when the role repeats (``coordinator-2``).
    coordinator = stage.partition("-")[0] == StageRole.COORDINATOR
    who = "the coordinator" if purpose == GATE and coordinator else "you"
    return f"Waits for {who} · {what}"
