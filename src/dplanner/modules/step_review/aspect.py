"""The review rounds aspect: the conversation a step holds with the steps it takes work from.

It is kept on the step that **asks** — a review, or a collector sending work back upstream —
because that step owns the questions and the cap on how many it may ask. Each round names
its **party** (the step answering) and holds only texts and the moments they were said:
``opened``, the findings and ``posted``, ``taken``, the reply and ``replied``, and the end —
``approved``, or ``escalated`` with a note for a person. A round's state and whose turn it
is are **derived from which stamps are there**, never stored, so a round cannot claim to
be at a stage its stamps disagree with, and every reader — the verbs, ``review wait``, the
Review tab — reads the same answer.

Rows are appended by the verbs in ``cli.py`` and stamped in place; a row this build cannot
read is skipped, and a key it does not know is kept when the row is stamped again.

**A turn whose agent has gone is due, once.** When the side with the turn has no agent run,
a window that launches what becomes due relaunches it (:func:`due_turns`) and stamps the
round with *which* turn it launched for — ``asker_turn_launched`` or
``party_turn_launched`` holding the stamp that began that turn — so the next settle, another
window or the terminal reads the same answer and nobody launches it twice. The stamp names
the turn rather than the moment, so a clock ahead or behind on the other machine cannot make
a launched turn read as due again. The window writes that stamp and nothing else here: it
never posts.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.planning.status import Status

MODULE_ID = "review_rounds"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

ROUNDS_KEY: Final = "rounds"
WITH_KEY: Final = "with"

# A round's states, in the order it moves through them; the last two end the conversation.
OPEN: Final = "open"
POSTED: Final = "posted"
TAKEN: Final = "taken"
REPLIED: Final = "replied"
APPROVED: Final = "approved"
ESCALATED: Final = "escalated"
ENDED_STATES: Final = (APPROVED, ESCALATED)

# The turn-launch stamp's origin: no view claims it, so every surface repaints.
TURN_LAUNCH_ORIGIN: Final[object] = object()

# Whose turn it is.
ASKER: Final = "asker"
PARTY: Final = "party"
ENDED: Final = "ended"


@dataclass(frozen=True)
class Round:
    """One round with one party, numbered among that party's rounds from 1."""

    party: StepId
    number: int
    opened: str
    findings: str = ""
    posted: str = ""
    taken: str = ""
    reply: str = ""
    replied: str = ""
    approved: str = ""
    escalated: str = ""
    note: str = ""
    # Which turn a window launched each side for: the stamp that began it (see below).
    asker_turn_launched: str = ""
    party_turn_launched: str = ""

    @property
    def state(self) -> str:
        """The furthest stamp — an approval over an escalation, since a person approving an
        escalated review is how that ends."""
        for state, stamp in (
            (APPROVED, self.approved),
            (ESCALATED, self.escalated),
            (REPLIED, self.replied),
            (TAKEN, self.taken),
            (POSTED, self.posted),
        ):
            if stamp:
                return state
        return OPEN


@dataclass(frozen=True)
class Message:
    """Something one side said: findings or an outcome from the asker, a reply from the
    party. What the Review tab lists and ``review wait`` prints."""

    round: Round
    sender: str  # ASKER or PARTY
    kind: str  # POSTED, REPLIED, APPROVED or ESCALATED
    text: str
    at: str


def began(held: Round) -> str:
    """The stamp that began the turn standing in ``held``: the findings for the party's, the
    reply — else the opening — for the asker's."""
    return held.posted if turn(held) == PARTY else (held.replied or held.opened)


def turn(last: Round | None) -> str:
    """Whose turn it is, after the last round with a party: the asker's to open or judge a
    round, the party's to answer one, or nobody's once the conversation has ended."""
    if last is None:
        return ASKER
    if last.state in ENDED_STATES:
        return ENDED
    return PARTY if last.state in (POSTED, TAKEN) else ASKER


def _rows(step: Step) -> list[dict[str, Any]]:
    stored = (step.module_data.get(MODULE_ID) or {}).get(ROUNDS_KEY)
    if not isinstance(stored, list):
        return []
    return [row for row in stored if isinstance(row, dict) and _readable(row)]


def _readable(row: dict[str, Any]) -> bool:
    return isinstance(row.get(WITH_KEY), str) and isinstance(row.get("opened"), str)


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""


def rounds(step: Step) -> list[Round]:
    """Every round the step has asked, in the order they were opened."""
    counts: dict[StepId, int] = {}
    found = []
    for row in _rows(step):
        party = row[WITH_KEY]
        counts[party] = counts.get(party, 0) + 1
        found.append(
            Round(
                party=party,
                number=counts[party],
                opened=row["opened"],
                findings=_text(row, "findings"),
                posted=_text(row, "posted"),
                taken=_text(row, "taken"),
                reply=_text(row, "reply"),
                replied=_text(row, "replied"),
                approved=_text(row, "approved"),
                escalated=_text(row, "escalated"),
                note=_text(row, "note"),
                asker_turn_launched=_text(row, "asker_turn_launched"),
                party_turn_launched=_text(row, "party_turn_launched"),
            )
        )
    return found


def with_party(step: Step, party: StepId) -> list[Round]:
    return [held for held in rounds(step) if held.party == party]


def last(step: Step, party: StepId) -> Round | None:
    held = with_party(step, party)
    return held[-1] if held else None


def opened(step: Step, party: StepId, at: str) -> dict[str, Any]:
    """The step's entry with a new round opened with ``party``."""
    return _entry([*_rows(step), {WITH_KEY: party, "opened": at}])


def said(step: Step, party: StepId, **fields: str) -> dict[str, Any]:
    """The step's entry with ``fields`` set on its last round with ``party`` — the one
    being answered or judged. Keys this build does not know are kept."""
    rows = [dict(row) for row in _rows(step)]
    for row in reversed(rows):
        if row[WITH_KEY] == party:
            row.update(fields)
            break
    else:
        raise ValueError(f"no round with {party}")
    return _entry(rows)


def turn_launched(step: Step, party: StepId) -> dict[str, Any]:
    """The step's entry with its last round with ``party`` stamped as launched for the turn
    standing in it — the claim an unattended launch makes, so the turn is due once."""
    held = last(step, party)
    if held is None:
        raise ValueError(f"no round with {party}")
    return said(step, party, **{f"{turn(held)}_turn_launched": began(held)})


def record_turn_launched(library: Library, asker: StepId, party: StepId) -> None:
    """Stamp the conversation's standing turn as launched — directly, off the undo stack,
    as the launch stamp itself is: a shell now exists, and Ctrl+Z cannot take it back."""
    entry = turn_launched(library.step(asker), party)
    SetModuleDataCommand(asker, MODULE_ID, entry, view_origin=TURN_LAUNCH_ORIGIN).redo(library)


def _entry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return stamped({ROUNDS_KEY: rows}, DATA_FORMAT.version)


def messages(held: Sequence[Round]) -> list[Message]:
    """What was said across ``held``, in the order it was said within each round."""
    found = []
    for each in held:
        if each.posted:
            found.append(Message(each, ASKER, POSTED, each.findings, each.posted))
        if each.replied:
            found.append(Message(each, PARTY, REPLIED, each.reply, each.replied))
        if each.escalated:
            found.append(Message(each, ASKER, ESCALATED, each.note, each.escalated))
        if each.approved:
            found.append(Message(each, ASKER, APPROVED, "", each.approved))
    return found


def standing(last_round: Round | None, asker: str, party: str) -> str:
    """Where a conversation stands, in a sentence: ``asker`` and ``party`` are the two
    steps as the reader should see them named."""
    if last_round is None:
        return f"{asker} has not opened a round with {party}"
    number = f"round {last_round.number}"
    return {
        OPEN: f"{number} is open: {asker} is writing its findings",
        POSTED: f"{party} has {asker}'s findings for {number}",
        TAKEN: f"{party} is working on {asker}'s findings for {number}",
        REPLIED: f"{party} answered {number}: {asker}'s turn",
        APPROVED: f"{asker} approved {party} in {number}",
        ESCALATED: f"{asker} handed {number} to a person",
    }[last_round.state]


@dataclass(frozen=True)
class TurnDue:
    """A side of a conversation that has the turn and no agent: ``step`` is that side, the
    asker or the party, and ``asker`` and ``party`` say which conversation."""

    step: Step
    asker: StepId
    party: StepId


def due_turns(
    library: Library,
    project: Project,
    is_agent: Callable[[Step], bool],
    running: Callable[[Step], bool],
    status_for: Callable[[Step], Status],
) -> list[TurnDue]:
    """Every side in ``project`` whose turn it is, whose agent has gone, and whom nobody
    launched for this turn yet — in project order of the asker, then its parties.

    A side a person has finished or blocked is theirs: never due — nor one whose status this
    build cannot read, which ``status_for`` hands in as blocked (``status.held``): readiness
    reads a :class:`~dplanner.planning.status.Status` and nothing else. A conversation's first
    turn — the asker's, before any round — is not here: a review is due to *start* the way
    any step is, by what it waits on (``progression.due``).
    """
    found = []
    for asker in project.steps:
        for party_id in dict.fromkeys(held.party for held in rounds(asker)):
            held = last(asker, party_id)
            if held is None or not library.has(party_id):
                continue
            side = turn(held)
            if side == ENDED:
                continue
            step = asker if side == ASKER else library.step(party_id)
            launched = held.asker_turn_launched if side == ASKER else held.party_turn_launched
            if (
                launched == began(held)
                or not is_agent(step)
                or running(step)
                or status_for(step) in (Status.DONE, Status.BLOCKED)
            ):
                continue
            found.append(TurnDue(step, asker.id, party_id))
    return found


def forget_for_paste(
    _project: Project, steps: Sequence[Step], _remapped: Mapping[StepId, StepId]
) -> None:
    """A copied step carries no conversation: it was held by the original."""
    for step in steps:
        step.module_data.pop(MODULE_ID, None)


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when it has asked nothing."""
    held = rounds(step)
    if not held:
        return ""
    count = f"{len(held)} review round{'' if len(held) == 1 else 's'}"
    ended = held[-1].state
    return f"{count}, {ended}" if ended in ENDED_STATES else count


SPEC = AspectSpec(
    id=MODULE_ID,
    label="Review rounds",
    summary="The conversation a review — or a collector — holds with the step it takes"
    " work from: rounds of findings and replies, and how it ended.",
    data_format=DATA_FORMAT,
    phrase=summary,
)
