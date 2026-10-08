"""The question inbox: everything a run needs a person — or the coordinator — for, a file per
question (FORMAT.md's *The `questions` directory*).

```
<project dir>/
└── questions/                   beside ledger/, and not one of the store's plan entries
    └── 2026-10/                 the month it was asked
        └── 20261007T103341Z-e1f2a3b4.json        shown as Q-e1f2
```

**DPlanner never waits on a process for a person.** A headless turn that needs somebody ends,
and what it needed is written here; the answer resumes the same session. So a question must
outlive every process and be readable by whoever is to answer it: project data, in git,
outside ``PLAN_ENTRIES`` like the ledger, one file per question so two agents asking at once
add two files. Its body is Claude's ``AskUserQuestion`` shape exactly — question, header,
options with descriptions, ``multiSelect`` — and ``answer.answers`` is the shape Claude takes
back; ``dplanner question ask`` writes a list of one.

**A question has writers in sequence**: the asker creates it, the coordinator may escalate it,
whoever may answer it does, and only the run's own machine consumes the answer — the act that
makes it count. Each change is a read-modify-write under an OS lock (:func:`update`), so two
answers on one machine cannot both land; the transitions below refuse whatever the state no
longer allows. Nothing here resumes anything: that is the supervisor's, which consumes.
"""

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from dplanner.core.config_dir import config_dir
from dplanner.core.fsio import os_lock, write_atomic
from dplanner.domain.ledger import new_run_id
from dplanner.domain.model import now_stamp

QUESTIONS_DIR = "questions"
FORMAT = 1

DECISION = "decision"
PLAN_APPROVAL = "plan-approval"
PERMISSION = "permission"
BLOCKED = "blocked"
LIMIT = "limit"
KINDS = (DECISION, PLAN_APPROVAL, PERMISSION, BLOCKED, LIMIT)

OPEN = "open"
ESCALATED = "escalated"
ANSWERED = "answered"
CONSUMED = "consumed"
WITHDRAWN = "withdrawn"
# Still waiting on somebody: nothing has consumed or withdrawn it.
UNSETTLED = (OPEN, ESCALATED, ANSWERED)

PERSON = "person"
COORDINATOR = "coordinator"
CLOCK = "clock"  # Answers a limit question when its reset has passed, and nothing else.

# The answer that resumes a run parked on a limit or a block without waiting: the limit
# card's one option, and what `agent retry` answers.
RETRY_NOW = "Retry now"


@dataclass(frozen=True)
class Question:
    id: str
    project: str
    step: str
    asked: str  # ISO stamp, UTC.
    kind: str = DECISION
    # Claude's AskUserQuestion shape: [{question, header, multiSelect, options: [{label,
    # description}]}], kept as given so a hosted Claude's own question is written through.
    questions: tuple[Mapping[str, Any], ...] = ()
    run: str = ""  # The run it parks; "" for a playbook's gate.
    by: Mapping[str, str] = field(default_factory=dict)  # {callsign, harness, machine, host}
    body: str = ""  # The plan of a plan-approval, the denials of a permission.
    resets: str = ""  # For a limit: when the account comes back.
    # A playbook's question: its pass, the gate's stage id and attempt, and why it asks.
    pass_: str = ""
    stage: str = ""
    attempt: int = 0
    purpose: str = ""  # "gate", "round-cap", "escalation"; "" for an agent's own question.
    settings: Mapping[str, Any] = field(default_factory=dict)
    state: str = OPEN
    answer: Mapping[str, Any] = field(default_factory=dict)  # {id, answers, by: {kind, name}, at}
    escalated: Mapping[str, Any] = field(default_factory=dict)  # {at, by, why}
    # {at, run, turn}, or a playbook's {at, pass, stage, attempt}.
    consumed: Mapping[str, Any] = field(default_factory=dict)
    withdrawn: Mapping[str, Any] = field(default_factory=dict)  # {at, why}
    late: tuple[Mapping[str, Any], ...] = ()  # Answers that lost a merge: shown, never applied.

    @property
    def short(self) -> str:
        return short(self.id)

    @property
    def text(self) -> str:
        """The question in words: each of its questions, one per line."""
        return "\n".join(str(q.get("question", "")) for q in self.questions)

    @property
    def settled(self) -> bool:
        return self.state not in UNSETTLED

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "format": FORMAT,
            "id": self.id,
            "project": self.project,
            "step": self.step,
            "asked": self.asked,
            "kind": self.kind,
            "questions": [dict(q) for q in self.questions],
            "state": self.state,
        }
        # Absence encodes the default, FORMAT.md's rule.
        optional: dict[str, Any] = {
            "run": self.run,
            "by": dict(self.by),
            "body": self.body,
            "resets": self.resets,
            "pass": self.pass_,
            "stage": self.stage,
            "attempt": self.attempt,
            "purpose": self.purpose,
            "settings": _plain(self.settings),
            "answer": _plain(self.answer),
            "escalated": _plain(self.escalated),
            "consumed": _plain(self.consumed),
            "withdrawn": _plain(self.withdrawn),
            "late": [dict(answer) for answer in self.late],
        }
        data.update({key: value for key, value in optional.items() if value})
        return data

    @classmethod
    def from_json(cls, raw: object) -> "Question | None":
        """A stored question, or None for one this build cannot read."""
        if not isinstance(raw, dict) or not isinstance(raw.get("format"), int):
            return None
        if raw["format"] > FORMAT:
            return None
        id_, project, step = _text(raw, "id"), _text(raw, "project"), _text(raw, "step")
        if not (id_ and project and step):
            return None
        given = raw.get("questions")
        late = raw.get("late")
        by = raw.get("by")
        attempt = raw.get("attempt")
        return cls(
            id=id_,
            project=project,
            step=step,
            asked=_text(raw, "asked"),
            kind=_text(raw, "kind") or DECISION,
            questions=tuple(q for q in given if isinstance(q, dict))
            if isinstance(given, list)
            else (),
            run=_text(raw, "run"),
            by={str(k): str(v) for k, v in by.items()} if isinstance(by, dict) else {},
            body=_text(raw, "body"),
            resets=_text(raw, "resets"),
            pass_=_text(raw, "pass"),
            stage=_text(raw, "stage"),
            attempt=attempt if isinstance(attempt, int) and not isinstance(attempt, bool) else 0,
            purpose=_text(raw, "purpose"),
            settings=_mapping(raw, "settings"),
            state=_text(raw, "state") or OPEN,
            answer=_mapping(raw, "answer"),
            escalated=_mapping(raw, "escalated"),
            consumed=_mapping(raw, "consumed"),
            withdrawn=_mapping(raw, "withdrawn"),
            late=tuple(a for a in late if isinstance(a, dict)) if isinstance(late, list) else (),
        )


def short(id_: str) -> str:
    """``Q-e1f2``: the first four of an id's random half, for a person to type."""
    return "Q-" + id_.rpartition("-")[2][:4]


def one(question: str, header: str = "", options: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
    """One question in AskUserQuestion's shape: what ``dplanner question ask`` writes a list of."""
    return {
        "question": question,
        "header": header,
        "multiSelect": False,
        "options": [{"label": label, "description": said} for label, said in options],
    }


def asked(
    project: str,
    step: str,
    at: str,
    questions: Sequence[Mapping[str, Any]],
    *,
    kind: str = DECISION,
    run: str = "",
    by: Mapping[str, str] | None = None,
    body: str = "",
    resets: str = "",
    pass_: str = "",
    stage: str = "",
    attempt: int = 0,
    purpose: str = "",
    settings: Mapping[str, Any] | None = None,
) -> Question:
    """A new open question, its id minted as a run's is. A playbook's gate, round cap or
    escalation names its ``pass_``, ``stage``, ``attempt`` and ``purpose`` instead of a run."""
    return Question(
        id=new_run_id(),
        project=project,
        step=step,
        asked=at,
        kind=kind,
        questions=tuple(questions),
        run=run,
        by=dict(by or {}),
        body=body,
        resets=resets,
        pass_=pass_,
        stage=stage,
        attempt=attempt,
        purpose=purpose,
        settings=dict(settings or {}),
    )


# -- what may happen to one ---------------------------------------------------------------------


# The gates only a person answers: a `person` stage, and a `progress` that could not merge on
# its own — on the mainline a person merges, and an agent's *pass* would stand in for them.
PERSON_ONLY = (PERSON, "progress")


def may_answer(question: Question, by_kind: str) -> str:
    """Why ``by_kind`` may not answer this question, or "" when it may. A person may answer
    anything; the coordinator may not answer a ``person`` gate — that gate is the playbook's
    promise that a person looked — and must escalate it instead."""
    if by_kind == COORDINATOR and question.purpose == "gate" and gate_role(question) in PERSON_ONLY:
        return f"{question.short} is a person gate: the coordinator escalates it, never answers"
    return ""


def gate_role(question: Question) -> str:
    """The kind of stage a gate question stands for: its stage id without the number a
    repeated stage carries (``person-2`` is a ``person`` gate)."""
    head, _, tail = question.stage.rpartition("-")
    return head if head and tail.isdigit() else question.stage


def answered(
    question: Question, answers: Mapping[str, str], by: Mapping[str, str], at: str
) -> Question:
    """The question with its answer — refused once it has one, or is settled."""
    _refuse_settled(question)
    if question.state == ANSWERED:
        who = question.answer.get("by", {}).get("name", "somebody")
        raise ValueError(f"{question.short} is already answered (by {who})")
    answer = {"id": new_run_id(), "answers": dict(answers), "by": dict(by), "at": at}
    return replace(question, state=ANSWERED, answer=answer)


def escalated(question: Question, by: Mapping[str, str], why: str, at: str) -> Question:
    """The question passed to a person — only an open one: an answer already given stands."""
    if question.state != OPEN:
        raise ValueError(f"{question.short} is {question.state}; only an open question escalates")
    return replace(question, state=ESCALATED, escalated={"at": at, "by": dict(by), "why": why})


def consumed(question: Question, at: str, run: str, turn: int) -> Question:
    """The answer acted on: the turn of the run it resumed. Terminal."""
    if question.state != ANSWERED:
        raise ValueError(f"{question.short} is {question.state}, not answered")
    return replace(question, state=CONSUMED, consumed={"at": at, "run": run, "turn": turn})


def settled_by_pass(question: Question, at: str) -> Question:
    """A playbook's answer acted on by its pass's engine: the pass, stage and attempt it
    settled. Terminal."""
    if question.state != ANSWERED:
        raise ValueError(f"{question.short} is {question.state}, not answered")
    settled = {
        "at": at,
        "pass": question.pass_,
        "stage": question.stage,
        "attempt": question.attempt,
    }
    return replace(question, state=CONSUMED, consumed=settled)


def withdrawn(question: Question, why: str, at: str) -> Question:
    """The question no longer stands — its run ended, or went on without it. Terminal."""
    _refuse_settled(question)
    return replace(question, state=WITHDRAWN, withdrawn={"at": at, "why": why})


def _refuse_settled(question: Question) -> None:
    if question.settled:
        raise ValueError(f"{question.short} is {question.state}")


def answers_for(question: Question, given: str) -> dict[str, str]:
    """``given`` as the answer to the question's one question: an option's own label when it
    names one (any case), else the words themselves."""
    if len(question.questions) != 1:
        raise ValueError(f"{question.short} asks {len(question.questions)} questions, not one")
    (asked_,) = question.questions
    labels = [str(o.get("label", "")) for o in asked_.get("options", []) if isinstance(o, dict)]
    chosen = next((label for label in labels if label.lower() == given.strip().lower()), given)
    return {str(asked_.get("question", "")): chosen}


def answer_text(question: Question) -> str:
    """The words a session resumes with: each question it asked and the answer given."""
    given = question.answer.get("answers", {})
    lines = [f"The answer to your question {question.short}:"]
    for asked_ in question.questions:
        text = str(asked_.get("question", ""))
        lines.append(f"> {text}\n{given.get(text, '(no answer)')}")
    return "\n\n".join(lines)


# -- the files ----------------------------------------------------------------------------------


def path_for(project_dir: Path, question: Question) -> Path:
    month = question.asked[:7] if len(question.asked) >= 7 else "unknown"
    return project_dir / QUESTIONS_DIR / month / f"{question.id}.json"


def write(project_dir: Path, question: Question) -> None:
    path = path_for(project_dir, question)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps(question.to_json(), indent=2, sort_keys=True) + "\n")


def records(project_dir: Path) -> list[Question]:
    """Every question of the project this build can read, oldest first."""
    found = [q for path in _files(project_dir) if (q := _load(path)) is not None]
    return sorted(found, key=lambda q: (q.asked, q.id))


def of_run(project_dir: Path, run: str) -> list[Question]:
    return [q for q in records(project_dir) if q.run == run]


def find(project_dir: Path, id_: str) -> Question | None:
    for path in (project_dir / QUESTIONS_DIR).glob(f"*/{id_}.json"):
        question = _load(path)
        if question is not None and question.id == id_:
            return question
    return None


def resolve(project_dir: Path, ref: str) -> Question:
    """A question by its id, its ``Q-e1f2`` or a unique start of either half of its id."""
    ref = ref.strip()
    key = ref[2:] if ref.upper().startswith("Q-") else ref
    found = [
        q
        for q in records(project_dir)
        if q.id == ref or q.id.startswith(key) or q.id.rpartition("-")[2].startswith(key.lower())
    ]
    if not key or not found:
        raise LookupError(f"no question {ref!r} in this project")
    if len(found) > 1:
        raise LookupError(f"{ref!r} names several questions: {', '.join(q.id for q in found)}")
    return found[0]


def update(
    project_dir: Path,
    id_: str,
    change: Callable[[Question], Question],
    config: Path | None = None,
) -> Question:
    """Read the question, change it and write it back, under :func:`held`. ``change`` raises
    to refuse."""
    with held(id_, config):
        question = find(project_dir, id_)
        if question is None:
            raise LookupError(f"no question {id_} in {project_dir}")
        changed = change(question)
        if changed != question:
            write(project_dir, changed)
        return changed


@contextmanager
def held(id_: str, config: Path | None = None) -> Iterator[None]:
    """The question's OS lock — in ``config``, never the plan, so a lock file is never
    committed. Whoever changes the question holds it; a run's record lock, when both are
    needed, is taken first."""
    with os_lock((config or config_dir()) / QUESTIONS_DIR / f"{id_}.lock", wait=True):
        yield


def withdraw_unsettled(
    project_dir: Path,
    run: str,
    why: str,
    keep: str = "",
    config: Path | None = None,
    states: Sequence[str] = UNSETTLED,
) -> None:
    """Withdraw the run's questions in ``states`` but ``keep``: it ended, asked again, or went
    on without them. By default one answered meanwhile is withdrawn too — the run is no
    longer parked on it, so no turn will consume it; an automatic retry, which may yet park
    on it, passes the open states alone."""

    def withdrawing(question: Question) -> Question:
        return withdrawn(question, why, now_stamp()) if question.state in states else question

    for question in of_run(project_dir, run):
        if question.state in states and question.id != keep:
            with suppress(LookupError):
                update(project_dir, question.id, withdrawing, config)


def fingerprint(project_dir: Path) -> tuple[tuple[str, int], ...]:
    """What the inbox looks like on disk, cheaply: a view polls this, since nothing watches
    the directory."""
    stamps: list[tuple[str, int]] = []
    for path in _files(project_dir):
        try:
            stamps.append((path.name, path.stat().st_mtime_ns))
        except OSError:
            continue
    return tuple(stamps)


def _files(project_dir: Path) -> Iterator[Path]:
    root = project_dir / QUESTIONS_DIR
    if not root.is_dir():
        return iter(())
    # The dot excludes write_atomic's temporaries, which sit beside the file they become.
    return iter(sorted(p for p in root.glob("*/*.json") if not p.name.startswith(".")))


def _load(path: Path) -> Question | None:
    try:
        return Question.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None  # A half-written file, or one a newer build wrote.


def _plain(value: Mapping[str, Any]) -> dict[str, Any]:
    return dict(value)


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}
