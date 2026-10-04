"""``dplanner review …`` — a review step and its conversation, driven from two terminals.

The step that **asks** — a review, or a collector sending work back upstream — opens a round
with ``start`` and says what it found with ``post``; the step that **answers** acknowledges
with ``take`` and answers with ``reply``; ``wait`` blocks either side until it is its turn.
A review ends it: ``approve`` finishes the reviewed step and leaves the review ready to
merge, carrying the reviewed step's PR, and ``escalate`` hands it to a person. Who a step
may talk to is who it takes work from review on — a review's subject, a collector's
auto-progress sources — so ``--to`` and ``--from`` default to the only one.

Each verb is one command in one run, and each status it moves goes through the same writer
``status set`` uses, so a finished step's at-work claim ends exactly as it would there.
``review wait`` holds nothing open while it waits: it reads the plan afresh from disk on
every poll, so the other side's writes are what it sees.
"""

import time
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from dplanner.cli import CliCommand, CliContext, CliError
from dplanner.cli.authoring import StepAuthor, StepAuthored
from dplanner.cli.lint import LintCheck, LintFinding
from dplanner.cli.lookup import body_from, find_step, step_arg
from dplanner.domain.agents import AgentHarness
from dplanner.domain.commands import Command, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step, now_stamp
from dplanner.domain.shelf import turn_off
from dplanner.domain.store import FilesFor, LibraryStore
from dplanner.modules.step_review.aspect import (
    DEFAULT_AGENT,
    MODULE_ID,
    ReviewSettings,
    is_review,
    lens_words,
    no_review,
    settings,
    subjects,
    write,
)
from dplanner.modules.step_review.rounds import (
    APPROVED,
    ASKER,
    ENDED,
    ESCALATED,
    OPEN,
    PARTY,
    POSTED,
    REPLIED,
    TAKEN,
    Round,
    last,
    opened,
    rounds,
    said,
    standing,
    turn,
    with_party,
)
from dplanner.modules.step_review.rounds import MODULE_ID as ROUNDS_ID
from dplanner.planning.status import REVIEW_AND_MERGE, Status, Unknown, word

# How long `review wait` blocks by default: under the ten minutes an agent CLI's tool call
# may run, so the agent that waits is never killed mid-wait by its own harness.
DEFAULT_TIMEOUT_S = 540
# How often it reads the plan again. A whole library loads in tens of milliseconds.
POLL_S = 2.0
# What `review wait` exits with when nothing arrived in time: not a refusal, not success.
TIMED_OUT = 3

DEFAULT_WORD = "default"
NO_LENSES = "none"

SetStatus = Callable[[CliContext, Step, Status], bool]


@dataclass(frozen=True)
class _Talk:
    """One conversation: the step that asks, the step that answers, and its last round."""

    asker: Step
    party: Step
    last: Round | None


def commands(
    *,
    auto_progresses: Callable[[Step, Step], bool],
    status_for: Callable[[Step], Status | Unknown],
    set_status: SetStatus,
    inherit_refs: Callable[[Step, Step], Command | None],
    note_escalation: Callable[[CliContext, Step, str, str], str],
    works_nobody: Callable[[Step], str],
    key_of: Callable[[Step], str],
    harnesses: Sequence[AgentHarness],
) -> list[CliCommand]:
    """Every reader here is another module's, handed over by the composition root:
    ``auto_progresses`` is who a step takes work from review on; ``set_status`` writes a
    status as ``status set`` does and ends a stopped step's claim; ``inherit_refs`` is the
    command copying one step's GitHub refs onto another; ``note_escalation`` keeps a note
    for a person on the review and answers its id."""
    talk = _Conversations(auto_progresses, status_for, key_of)

    def run_set(context: CliContext, args: Namespace) -> int:
        return _set(context, args, works_nobody, harnesses)

    def run_show(context: CliContext, args: Namespace) -> int:
        return _show(context, args, talk, harnesses)

    def run_start(context: CliContext, args: Namespace) -> int:
        return _start(context, args, talk)

    def run_post(context: CliContext, args: Namespace) -> int:
        return _post(context, args, talk, set_status)

    def run_take(context: CliContext, args: Namespace) -> int:
        return _take(context, args, talk)

    def run_reply(context: CliContext, args: Namespace) -> int:
        return _reply(context, args, talk, set_status)

    def run_approve(context: CliContext, args: Namespace) -> int:
        return _approve(context, args, talk, set_status, inherit_refs)

    def run_escalate(context: CliContext, args: Namespace) -> int:
        return _escalate(context, args, talk, set_status, note_escalation)

    def run_wait(context: CliContext, args: Namespace) -> int:
        return _wait(context, args, talk)

    return [
        CliCommand(
            path=("review", "set"),
            summary="Make a step an automatic review of the step it waits on, and say who "
            "reviews, through which lenses, in how many rounds at most.",
            configure=lambda parser: _configure_set(parser, harnesses),
            run=run_set,
            examples=(
                "dplanner review set R12 --agent codex --lens architecture --lens perf",
                "dplanner review set R12 --max-rounds 2",
            ),
        ),
        CliCommand(
            path=("review", "clear"),
            summary="The step is no longer a review; its settings are shelved.",
            configure=step_arg,
            run=_clear,
            examples=("dplanner review clear R12",),
        ),
        CliCommand(
            path=("review", "show"),
            summary="A review's settings, and every conversation a step asks or answers.",
            configure=step_arg,
            run=run_show,
            examples=("dplanner review show R12", "dplanner review show S3 --json"),
        ),
        CliCommand(
            path=("review", "start"),
            summary="Open a round with the step this one reviews or collects; refused past "
            "the round cap.",
            configure=lambda parser: _configure_asker(parser, text=False),
            run=run_start,
            examples=("dplanner review start R12", "dplanner review start C9 --to S4"),
        ),
        CliCommand(
            path=("review", "post"),
            summary="Post the open round's findings; the reviewed step is in progress again.",
            configure=lambda parser: _configure_asker(parser, text=True),
            run=run_post,
            examples=("dplanner review post R12 --file findings.md",),
        ),
        CliCommand(
            path=("review", "take"),
            summary="Take the findings posted to this step, and print them.",
            configure=_configure_party,
            run=run_take,
            examples=("dplanner review take S3",),
        ),
        CliCommand(
            path=("review", "reply"),
            summary="Answer the findings; the step is ready for review again.",
            configure=lambda parser: _configure_party(parser, text=True),
            run=run_reply,
            examples=("dplanner review reply S3 --file reply.md",),
        ),
        CliCommand(
            path=("review", "approve"),
            summary="Accept the reviewed work: it is done, and the review is ready to merge "
            "carrying its branch and PR.",
            configure=lambda parser: _configure_asker(parser, text=False),
            run=run_approve,
            examples=("dplanner review approve R12",),
        ),
        CliCommand(
            path=("review", "escalate"),
            summary="Hand the review to a person: it is blocked, with a note saying what "
            "they must decide.",
            configure=lambda parser: _configure_asker(parser, text=True),
            run=run_escalate,
            examples=("dplanner review escalate R12 --text 'The two disagree on the schema'",),
        ),
        CliCommand(
            path=("review", "wait"),
            summary="Block until it is this step's turn in its review, or the review ends; "
            "exit 3 when the time runs out.",
            configure=_configure_wait,
            run=run_wait,
            examples=(
                "dplanner review wait S3",
                "dplanner review wait R12 --timeout 300",
            ),
        ),
    ]


# -- arguments --------------------------------------------------------------------------------


def _configure_set(parser: ArgumentParser, harnesses: Sequence[AgentHarness]) -> None:
    step_arg(parser)
    parser.add_argument(
        "--agent",
        choices=[DEFAULT_WORD, *(harness.id for harness in harnesses)],
        help="who reviews: an agent CLI, or default for the default launch profile",
    )
    parser.add_argument(
        "--lens",
        action="append",
        metavar="NAME",
        help="a lens to review through — architecture, security, or a skill of your own; "
        f"repeat for several, which replace the list; {NO_LENSES} for none",
    )
    parser.add_argument(
        "--max-rounds", type=int, metavar="N", help="rounds before a person decides (3)"
    )


def _text_arguments(parser: ArgumentParser) -> None:
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--text", help="what to say, inline")
    body.add_argument("--file", help="a markdown file holding it, or - for stdin")


def _configure_asker(parser: ArgumentParser, *, text: bool) -> None:
    step_arg(parser)
    parser.add_argument(
        "--to", metavar="STEP", help="the step it talks to, when it takes work from several"
    )
    if text:
        _text_arguments(parser)


def _configure_party(parser: ArgumentParser, *, text: bool = False) -> None:
    step_arg(parser)
    parser.add_argument(
        "--from",
        dest="from_",
        metavar="STEP",
        help="the review or collector it answers, when several take its work",
    )
    if text:
        _text_arguments(parser)


def _configure_wait(parser: ArgumentParser) -> None:
    step_arg(parser)
    counterpart = parser.add_mutually_exclusive_group()
    counterpart.add_argument("--to", metavar="STEP", help="wait as the step that asks")
    counterpart.add_argument(
        "--from", dest="from_", metavar="STEP", help="wait as the step that answers"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        metavar="SECONDS",
        help=f"give up after this long, exiting {TIMED_OUT} ({DEFAULT_TIMEOUT_S})",
    )


def _said(args: Namespace, missing: str) -> str:
    text = (body_from(args.file) if args.file is not None else args.text or "").strip()
    if not text:
        raise CliError(missing)
    return text


# -- who talks to whom ------------------------------------------------------------------------


class _Conversations:
    """Who a step talks to, and how each of them is named — the readers the verbs share."""

    def __init__(
        self,
        auto_progresses: Callable[[Step, Step], bool],
        status_for: Callable[[Step], Status | Unknown],
        key_of: Callable[[Step], str],
    ) -> None:
        self.auto_progresses = auto_progresses
        self.status_for = status_for
        self.key_of = key_of

    def named(self, step: Step) -> str:
        return f"{self.key_of(step)} {step.title}".strip()

    def ref(self, step: Step) -> str:
        return self.key_of(step) or repr(step.title)

    def parties(self, library: Library, asker: Step) -> list[Step]:
        """The steps ``asker`` takes work from review on: whom it may send findings."""
        return [
            source for source in library.requires(asker.id) if self.auto_progresses(asker, source)
        ]

    def askers(self, library: Library, party: Step) -> list[Step]:
        """The steps that take ``party``'s work from review on: who may send it findings."""
        return [
            waiter for waiter in library.dependents(party.id) if self.auto_progresses(waiter, party)
        ]

    def party(self, context: CliContext, asker: Step, needle: str | None) -> Step:
        """``--to``, or the only step ``asker`` takes work from."""
        library = context.library
        found = self.parties(library, asker)
        if needle:
            named = find_step(library, needle, library.project_of(asker.id))
            if named not in found:
                raise CliError(
                    f"{self.ref(asker)} does not take {self.ref(named)}'s work from review "
                    f"on{self._among(found, 'it talks to')}"
                )
            return named
        if len(found) == 1:
            return found[0]
        if not found:
            raise CliError(
                f"{self.ref(asker)} takes no step's work from review on — a review talks to "
                f"the step it waits on (`dplanner step link {self.ref(asker)} <step>`), a "
                "collector to its auto-progress sources"
            )
        raise CliError(f"{self.ref(asker)} talks to {self._keys(found)} — name one with --to")

    def asker(self, context: CliContext, party: Step, needle: str | None) -> Step:
        """``--from``, or the only step that takes ``party``'s work — the only one waiting
        on an answer from it, when several take it."""
        library = context.library
        found = self.askers(library, party)
        if needle:
            named = find_step(library, needle, library.project_of(party.id))
            if named not in found:
                raise CliError(
                    f"{self.ref(named)} does not take {self.ref(party)}'s work from review "
                    f"on{self._among(found, 'these do')}"
                )
            return named
        if len(found) > 1:
            waiting = [each for each in found if turn(last(each, party.id)) == PARTY]
            found = waiting if len(waiting) == 1 else found
        if len(found) == 1:
            return found[0]
        if not found:
            raise CliError(f"no review or collector takes {self.ref(party)}'s work from review on")
        raise CliError(
            f"{self._keys(found)} all take {self.ref(party)}'s work — name one with --from"
        )

    def between(self, asker: Step, party: Step) -> _Talk:
        return _Talk(asker, party, last(asker, party.id))

    def standing(self, held: _Talk) -> str:
        return standing(held.last, self.ref(held.asker), self.ref(held.party))

    def _keys(self, steps: Sequence[Step]) -> str:
        return ", ".join(self.ref(step) for step in steps)

    def _among(self, steps: Sequence[Step], verb: str) -> str:
        return f" ({verb}: {self._keys(steps)})" if steps else ""


# -- the verbs --------------------------------------------------------------------------------


def _set(
    context: CliContext,
    args: Namespace,
    works_nobody: Callable[[Step], str],
    harnesses: Sequence[AgentHarness],
) -> int:
    step = find_step(context.library, args.step, context.current)
    if kind := works_nobody(step):
        raise CliError(f"{step.title!r} is {kind}: {no_review(kind)}")
    chosen = settings(step)
    if args.agent is not None:
        chosen = replace(chosen, agent=DEFAULT_AGENT if args.agent == DEFAULT_WORD else args.agent)
    if args.lens is not None:
        named = [lens.strip() for lens in args.lens if lens.strip()]
        chosen = replace(chosen, lenses=() if named == [NO_LENSES] else tuple(dict.fromkeys(named)))
    if args.max_rounds is not None:
        if args.max_rounds < 1:
            raise CliError("--max-rounds is at least 1: a review needs a round to say anything")
        chosen = replace(chosen, max_rounds=args.max_rounds)
    context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(chosen), label="Set Review"))
    context.report(
        {"step": step.id, "review": _settings_data(chosen)},
        f"{step.title}: {_settings_words(chosen, harnesses)}",
    )
    return 0


def _clear(context: CliContext, args: Namespace) -> int:
    step = find_step(context.library, args.step, context.current)
    if not is_review(step):
        context.report({"step": step.id, "review": None}, f"{step.title}: already no review")
        return 0
    context.apply(turn_off(step.id, MODULE_ID, label="Remove Review"))
    context.report({"step": step.id, "review": None}, f"{step.title}: no longer a review")
    return 0


def _show(
    context: CliContext, args: Namespace, talk: _Conversations, harnesses: Sequence[AgentHarness]
) -> int:
    library = context.library
    step = find_step(library, args.step, context.current)
    asked = [talk.between(step, party) for party in _asked_of(library, step, talk)]
    answered = [talk.between(asker, step) for asker in talk.askers(library, step)]
    lines = [talk.named(step)]
    if is_review(step):
        lines.append(f"  {_settings_words(settings(step), harnesses)}")
        if not subjects(library, step):
            lines.append("  reviews nothing yet — link it after the step it reviews")
    for held in [*asked, *answered]:
        lines.append(f"  {talk.standing(held)}")
        for each in with_party(held.asker, held.party.id):
            lines += _round_lines(each, held, talk)
    if len(lines) == 1:
        lines.append("  no review, and nothing reviewed")
    context.report(
        {
            "step": step.id,
            "review": _settings_data(settings(step)) if is_review(step) else None,
            "conversations": [_talk_data(held, talk) for held in [*asked, *answered]],
        },
        "\n".join(lines),
    )
    return 0


def _asked_of(library: Library, step: Step, talk: _Conversations) -> list[Step]:
    """Whom ``step`` talks to as the one asking: every party of a review, and whoever a
    collector has opened a round with."""
    parties = talk.parties(library, step)
    if is_review(step):
        return parties
    held = {each.party for each in rounds(step)}
    return [party for party in parties if party.id in held]


def _start(context: CliContext, args: Namespace, talk: _Conversations) -> int:
    asker = find_step(context.library, args.step, context.current)
    party = talk.party(context, asker, args.to)
    held = talk.between(asker, party)
    if held.last is not None and held.last.state in (OPEN, POSTED, TAKEN):
        raise CliError(f"{talk.standing(held)} — a round is answered before the next is opened")
    cap = settings(asker).max_rounds
    count = len(with_party(asker, party.id))
    if count >= cap:
        raise CliError(_at_the_cap(asker, party, cap, talk))
    context.apply(SetModuleDataCommand(asker.id, ROUNDS_ID, opened(asker, party.id, now_stamp())))
    number = count + 1
    context.report(
        {"step": asker.id, "party": party.id, "round": number, "max_rounds": cap},
        f"{talk.named(asker)}: round {number} of {cap} open with {talk.ref(party)} — post "
        f"what you find with `dplanner review post {talk.ref(asker)} --file <findings.md>`",
    )
    return 0


def _at_the_cap(asker: Step, party: Step, cap: int, talk: _Conversations) -> str:
    ref = talk.ref(asker)
    spent = f"{ref} has had its {cap} round{'' if cap == 1 else 's'} with {talk.ref(party)}"
    if is_review(asker):
        return (
            f"{spent} — accept the work: `dplanner review approve {ref}`, or hand it to a "
            f"person: `dplanner review escalate {ref} --text '<what they must decide>'`"
        )
    return (
        f"{spent} — land its work (`dplanner status set {talk.ref(party)} done`), or say "
        f"you are stuck (`dplanner status set {ref} blocked`)"
    )


def _post(context: CliContext, args: Namespace, talk: _Conversations, set_status: SetStatus) -> int:
    asker = find_step(context.library, args.step, context.current)
    party = talk.party(context, asker, args.to)
    held = talk.between(asker, party)
    if held.last is None or held.last.state != OPEN:
        raise CliError(_no_open_round(held, talk))
    findings = _said(args, "say what you found: --text, or --file <findings.md>")
    number = held.last.number
    context.apply(
        SetModuleDataCommand(
            asker.id, ROUNDS_ID, said(asker, party.id, findings=findings, posted=now_stamp())
        )
    )
    set_status(context, party, Status.IN_PROGRESS)
    context.report(
        {"step": asker.id, "party": party.id, "round": number, "state": POSTED},
        f"{talk.named(asker)}: round {number}'s findings posted to {talk.ref(party)}, which is "
        f"in progress again — it answers with `dplanner review reply {talk.ref(party)}`",
    )
    return 0


def _no_open_round(held: _Talk, talk: _Conversations) -> str:
    ref = talk.ref(held.asker)
    if held.last is not None and held.last.state in (POSTED, TAKEN):
        return f"{talk.standing(held)} — wait for its answer: `dplanner review wait {ref}`"
    return f"no round is open with {talk.ref(held.party)} — `dplanner review start {ref}` opens one"


def _take(context: CliContext, args: Namespace, talk: _Conversations) -> int:
    party = find_step(context.library, args.step, context.current)
    asker = talk.asker(context, party, args.from_)
    held = talk.between(asker, party)
    if held.last is None or held.last.state not in (POSTED, TAKEN):
        raise CliError(f"nothing to take: {talk.standing(held)}")
    number = held.last.number
    data = {
        "step": party.id,
        "asker": asker.id,
        "round": number,
        "state": TAKEN,
        "findings": held.last.findings,
    }
    if held.last.state == TAKEN:
        head = f"{talk.named(party)}: round {number} from {talk.ref(asker)}, already taken"
    else:
        context.apply(
            SetModuleDataCommand(asker.id, ROUNDS_ID, said(asker, party.id, taken=now_stamp()))
        )
        head = f"{talk.named(party)}: took round {number} from {talk.ref(asker)}"
    context.report(
        data,
        f"{head} — answer with `dplanner review reply {talk.ref(party)} --file <reply.md>`\n\n"
        f"{held.last.findings}",
    )
    return 0


def _reply(
    context: CliContext, args: Namespace, talk: _Conversations, set_status: SetStatus
) -> int:
    party = find_step(context.library, args.step, context.current)
    asker = talk.asker(context, party, args.from_)
    held = talk.between(asker, party)
    if held.last is None or held.last.state not in (POSTED, TAKEN):
        raise CliError(f"nothing to answer: {talk.standing(held)}")
    reply = _said(args, "say what you did about the findings: --text, or --file <reply.md>")
    number = held.last.number
    context.apply(
        SetModuleDataCommand(
            asker.id, ROUNDS_ID, said(asker, party.id, reply=reply, replied=now_stamp())
        )
    )
    set_status(context, party, Status.READY_FOR_REVIEW)
    context.report(
        {"step": party.id, "asker": asker.id, "round": number, "state": REPLIED},
        f"{talk.named(party)}: answered round {number} from {talk.ref(asker)}, and is ready "
        f"for review — wait for the verdict with `dplanner review wait {talk.ref(party)}`",
    )
    return 0


def _approve(
    context: CliContext,
    args: Namespace,
    talk: _Conversations,
    set_status: SetStatus,
    inherit_refs: Callable[[Step, Step], Command | None],
) -> int:
    asker = find_step(context.library, args.step, context.current)
    if not is_review(asker):
        raise CliError(_not_a_review(asker, "lands its sources' work itself", "done", talk))
    party = talk.party(context, asker, args.to)
    held = talk.between(asker, party)
    data = {"step": asker.id, "party": party.id}
    if held.last is not None and held.last.state == APPROVED:
        context.report(data, f"{talk.named(asker)}: already approved {talk.ref(party)}")
        return 0
    if turn(held.last) == PARTY:
        raise CliError(
            f"{talk.standing(held)} — approve once it answers (`dplanner review wait "
            f"{talk.ref(asker)}`), or hand it to a person with `dplanner review escalate`"
        )
    if held.last is None:  # Nothing to say: the review approves in a round of its own.
        context.apply(
            SetModuleDataCommand(asker.id, ROUNDS_ID, opened(asker, party.id, now_stamp()))
        )
    context.apply(
        SetModuleDataCommand(asker.id, ROUNDS_ID, said(asker, party.id, approved=now_stamp()))
    )
    set_status(context, party, Status.DONE)
    set_status(context, asker, Status.READY_TO_MERGE)
    refs = inherit_refs(party, asker)
    if refs is not None:
        context.apply(refs)
    carried = (
        f", carrying {talk.ref(party)}'s branch and PR"
        if refs is not None
        else f" — {talk.ref(party)} records no branch or PR to carry"
    )
    context.report(
        data | {"refs": refs is not None},
        f"{talk.named(asker)}: approved {talk.ref(party)}, which is done; the review is "
        f"ready to merge{carried}",
    )
    return 0


def _escalate(
    context: CliContext,
    args: Namespace,
    talk: _Conversations,
    set_status: SetStatus,
    note_escalation: Callable[[CliContext, Step, str, str], str],
) -> int:
    asker = find_step(context.library, args.step, context.current)
    if not is_review(asker):
        raise CliError(_not_a_review(asker, "says it is stuck", "blocked", talk, own=True))
    party = talk.party(context, asker, args.to)
    held = talk.between(asker, party)
    if held.last is not None and held.last.state == APPROVED:
        raise CliError(f"{talk.standing(held)} — there is nothing left to decide")
    why = _said(args, "say what a person must decide: --text, or --file <why.md>")
    if held.last is None:
        context.apply(
            SetModuleDataCommand(asker.id, ROUNDS_ID, opened(asker, party.id, now_stamp()))
        )
    context.apply(
        SetModuleDataCommand(
            asker.id, ROUNDS_ID, said(asker, party.id, escalated=now_stamp(), note=why)
        )
    )
    number = len(with_party(asker, party.id))
    set_status(context, asker, Status.BLOCKED)
    title = (
        f"{talk.ref(asker)}'s review of {talk.ref(party)} needs a person after "
        f"{number} round{'' if number == 1 else 's'}"
    )
    note = note_escalation(context, asker, title, why)
    context.report(
        {"step": asker.id, "party": party.id, "round": number, "note": note},
        f"{talk.named(asker)}: blocked, handed to a person — {note} says what they must decide",
    )
    return 0


def _not_a_review(
    step: Step, instead: str, word: str, talk: _Conversations, *, own: bool = False
) -> str:
    ref = talk.ref(step)
    target = ref if own else "<source>"
    return f"{ref} is not a review: a collector {instead} — `dplanner status set {target} {word}`"


# -- waiting ----------------------------------------------------------------------------------


def await_turn(
    load: Callable[[], Library],
    ready: Callable[[Library], bool],
    timeout: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    interval: float = POLL_S,
) -> tuple[Library, bool]:
    """Read the plan with ``load`` until ``ready`` says so or ``timeout`` seconds pass —
    the last reading, and whether it was ready. Nothing is held between readings."""
    deadline = clock() + timeout
    while True:
        library = load()
        if ready(library):
            return library, True
        left = deadline - clock()
        if left <= 0:
            return library, False
        sleep(min(interval, left))


def _wait(context: CliContext, args: Namespace, talk: _Conversations) -> int:
    library = context.library
    step = find_step(library, args.step, context.current)
    asking = args.to is not None or (args.from_ is None and (is_review(step) or bool(rounds(step))))
    if asking:
        pairs = [(step.id, other.id) for other in _counterparts_of_asker(context, step, args, talk)]
    else:
        pairs = [(other.id, step.id) for other in _counterparts_of_party(context, step, args, talk)]
    side = ASKER if asking else PARTY
    path = context.store.library_path

    def load() -> Library:
        store = LibraryStore(path)
        try:
            return store.load()
        finally:
            store.close()

    def talks(read: Library) -> list[_Talk]:
        found = []
        for asker_id, party_id in pairs:
            if not (read.has(asker_id) and read.has(party_id)):
                raise CliError("a step in this review was removed while waiting")
            found.append(talk.between(read.step(asker_id), read.step(party_id)))
        return found

    def ready(read: Library) -> bool:
        return any(_arrived(held, side, talk) for held in talks(read))

    read, arrived = await_turn(load, ready, max(args.timeout, 0))
    held = talks(read)
    data = {
        "step": step.id,
        "side": side,
        "arrived": arrived,
        "conversations": [_talk_data(each, talk) for each in held],
    }
    if arrived:
        text = "\n\n".join(
            _what_arrived(each, side, talk) for each in held if _arrived(each, side, talk)
        )
        context.report(data, text)
        return 0
    waited = "\n".join(f"  {talk.standing(each)}" for each in held)
    named = (
        f" --to {talk.ref(held[0].party)}"
        if args.to is not None
        else f" --from {talk.ref(held[0].asker)}"
        if args.from_ is not None
        else ""
    )
    context.report(
        data,
        f"Nothing yet after {args.timeout} s:\n{waited}\n"
        f"Wait again: `dplanner review wait {talk.ref(step)}{named}`",
    )
    return TIMED_OUT


def _counterparts_of_asker(
    context: CliContext, step: Step, args: Namespace, talk: _Conversations
) -> list[Step]:
    if args.to is not None:
        return [talk.party(context, step, args.to)]
    found = talk.parties(context.library, step)
    if not found:
        talk.party(context, step, None)  # Refuses, saying how a step gets one.
    return found


def _counterparts_of_party(
    context: CliContext, step: Step, args: Namespace, talk: _Conversations
) -> list[Step]:
    if args.from_ is not None:
        return [talk.asker(context, step, args.from_)]
    found = talk.askers(context.library, step)
    if not found:
        raise CliError(
            f"no review or collector takes {talk.ref(step)}'s work from review on — nothing "
            "to wait for"
        )
    return found


def _arrived(held: _Talk, side: str, talk: _Conversations) -> bool:
    """Whether it is ``side``'s turn, or the conversation has ended. The asker's first turn
    comes once the party's work is on offer — a review of unfinished work has nothing to
    read yet."""
    whose = turn(held.last)
    if whose == ENDED:
        return True
    if side == PARTY:
        return whose == PARTY
    if held.last is None:
        return talk.status_for(held.party) in {*REVIEW_AND_MERGE, Status.DONE}
    return whose == ASKER


def _what_arrived(held: _Talk, side: str, talk: _Conversations) -> str:
    asker, party = talk.ref(held.asker), talk.ref(held.party)
    last_round = held.last
    if last_round is None:
        return f"{party} is ready for review — open a round: `dplanner review start {asker}`"
    number = last_round.number
    state = last_round.state
    if state == APPROVED:
        return f"{asker} approved {party} in round {number}: {party} is done."
    if state == ESCALATED:
        return f"{asker} handed round {number} to a person:\n\n{last_round.note}"
    if side == PARTY:
        return (
            f"Round {number} from {asker}:\n\n{last_round.findings}\n\n"
            f"Take it with `dplanner review take {party}`, and answer with "
            f"`dplanner review reply {party} --file <reply.md>`."
        )
    if state == OPEN:
        return f"Round {number} with {party} is open — post: `dplanner review post {asker}`"
    cap = settings(held.asker).max_rounds
    after = (
        f"approve it (`dplanner review approve {asker}`) or open round {number + 1} "
        f"(`dplanner review start {asker}`)"
        if number < cap
        else f"that was the last of {cap} rounds: approve it (`dplanner review approve "
        f"{asker}`) or hand it to a person (`dplanner review escalate {asker}`)"
    )
    return f"{party} answered round {number}:\n\n{last_round.reply}\n\nNow {after}."


# -- how it is said ---------------------------------------------------------------------------


def _agent_words(agent: str, harnesses: Sequence[AgentHarness]) -> str:
    if agent == DEFAULT_AGENT:
        return "the default profile"
    for harness in harnesses:
        if harness.id == agent:
            return harness.label
    return f"{agent} (not an agent this build knows)"


def _settings_words(chosen: ReviewSettings, harnesses: Sequence[AgentHarness]) -> str:
    rounds_word = "round" if chosen.max_rounds == 1 else "rounds"
    return (
        f"reviewed by {_agent_words(chosen.agent, harnesses)}, through "
        f"{lens_words(chosen.lenses)}, {chosen.max_rounds} {rounds_word} at most"
    )


def _settings_data(chosen: ReviewSettings) -> dict[str, object]:
    return {
        "agent": chosen.agent or DEFAULT_WORD,
        "lenses": list(chosen.lenses),
        "max_rounds": chosen.max_rounds,
    }


def _round_lines(each: Round, held: _Talk, talk: _Conversations) -> list[str]:
    lines = [f"    round {each.number}: {each.state}"]
    for said_by, text in (
        (talk.ref(held.asker), each.findings),
        (talk.ref(held.party), each.reply),
        (talk.ref(held.asker), each.note),
    ):
        if text:
            first = text.strip().splitlines()[0]
            lines.append(f"      {said_by}: {first}")
    return lines


def _talk_data(held: _Talk, talk: _Conversations) -> dict[str, object]:
    return {
        "asker": held.asker.id,
        "asker_key": talk.key_of(held.asker),
        "party": held.party.id,
        "party_key": talk.key_of(held.party),
        "party_status": word(talk.status_for(held.party)),
        "turn": turn(held.last),
        "standing": talk.standing(held),
        "rounds": [
            {
                "round": each.number,
                "state": each.state,
                "opened": each.opened,
                "findings": each.findings,
                "posted": each.posted,
                "taken": each.taken,
                "reply": each.reply,
                "replied": each.replied,
                "approved": each.approved,
                "escalated": each.escalated,
                "note": each.note,
            }
            for each in with_party(held.asker, held.party.id)
        ],
    }


# -- authoring and lint -----------------------------------------------------------------------


def step_author() -> StepAuthor:
    """``step add``'s ``--review``: the new step reviews what it waits on, as a review with
    the default settings — ``review set`` changes them."""

    def configure(parser: ArgumentParser) -> None:
        parser.add_argument(
            "--review",
            action="store_true",
            help="the step reviews its --after step: an automatic review (add --agent)",
        )

    def author(context: CliContext, step: Step, args: Namespace) -> StepAuthored | None:
        if not args.review:
            return None
        context.apply(SetModuleDataCommand(step.id, MODULE_ID, write(ReviewSettings())))
        return StepAuthored({"review": True}, "review")

    return StepAuthor(configure, author)


def lint_checks(
    *,
    is_agent: Callable[[Step], bool],
    key_of: Callable[[Step], str],
    harnesses: Sequence[AgentHarness],
) -> list[LintCheck]:
    """What a review can be wrong about: whom it reviews, who reviews, and a step that
    goes round it."""

    def ref(step: Step) -> str:
        return key_of(step) or repr(step.title)

    def finding(check: str, step: Step, message: str) -> LintFinding:
        return LintFinding(check=check, subject_id=step.id, subject=step.title, message=message)

    def reviews(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        known = {harness.id for harness in harnesses}
        found = []
        for step in project.steps:
            if not is_review(step):
                continue
            reviewed = subjects(library, step)
            if not reviewed:
                found.append(
                    finding(
                        "review.subject",
                        step,
                        "reviews nothing — link it after the step it reviews: "
                        f"`dplanner step link {ref(step)} <step>`",
                    )
                )
            elif len(reviewed) > 1:
                keys = ", ".join(ref(each) for each in reviewed)
                found.append(
                    finding(
                        "review.subject",
                        step,
                        f"reviews {keys} at once — a review takes one subject; give each its "
                        f"own review (`dplanner step unlink {ref(step)} <step>`)",
                    )
                )
            if not is_agent(step):
                found.append(
                    finding(
                        "review.agent",
                        step,
                        "is a review, but no agent will pick it up — "
                        f"`dplanner agent on {ref(step)}`",
                    )
                )
            agent = settings(step).agent
            if agent != DEFAULT_AGENT and agent not in known:
                found.append(
                    finding(
                        "review.unknown-agent",
                        step,
                        f"is reviewed by {agent!r}, which is no agent this build knows — "
                        f"`dplanner review set {ref(step)} --agent "
                        f"{'|'.join([DEFAULT_WORD, *sorted(known)])}`",
                    )
                )
        return found

    def bypassed(library: Library, project: Project, _files: FilesFor) -> list[LintFinding]:
        """A step waiting on reviewed work directly starts before the review has said a
        word about it; waiting on the review is what makes the review a gate."""
        found = []
        for review in project.steps:
            if not is_review(review):
                continue
            for reviewed in subjects(library, review):
                for waiter in library.dependents(reviewed.id):
                    if waiter.id == review.id or is_review(waiter):
                        continue
                    found.append(
                        finding(
                            "review.bypassed",
                            waiter,
                            f"waits on {ref(reviewed)} directly, not on its review "
                            f"{ref(review)} — `dplanner step unlink {ref(waiter)} "
                            f"{ref(reviewed)}`, then `dplanner step link {ref(waiter)} "
                            f"{ref(review)}`",
                        )
                    )
        return found

    return [reviews, bypassed]
