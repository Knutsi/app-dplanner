"""What can be launched right now, given the graph and what status claims are stored.

``ordering.py`` answers "in what order *could* this be done"; this answers "and where are
we". It is a different question from wave membership: a step deep in the graph whose
prerequisites have all been finished is launchable today, and no wave number says so. The
frontier here is a per-step check — every ``requires`` target reads done — not wave one,
and the two only coincide in a project where nothing has been finished yet.

**Readiness accepts a :class:`~dplanner.planning.status.Status` only.** ``status_for`` is a
function the caller supplies — the stored status, or the status on a day with waits read
in — and it answers in the vocabulary ``status.py`` owns, never a word. A reading this
walk must not guess at is turned into a status *before* it gets here, by ``status.held``:
a word this build cannot read holds the step as blocked — never due, in ``attention`` for a
person to look at, and not done, so nothing waits past it — and a wait not over is pending.
The types make the caller decide; reading an unknown word as pending would launch the step
again.

**Review and merge are on the board, and not done.** A step whose agent has finished waits
for a person (``ready-for-review``) or for its merge (``ready-to-merge``): it is claimed out
of the graph like a running step, counts as one move away for the lookahead, and frees
nothing — a plain ``requires`` is fulfilled by ``done`` alone, so nothing starts on work
nobody has accepted.

**Except across an auto-progress link.** A step that exists to take parallel work and land
it — three agents' branches merged by a fourth — cannot wait for its sources to be done,
because they are done only once it has landed them. ``auto_progresses(waiter, source)`` is
handed in like ``status_for`` (the module owning the flag owns its shape), and a source it
answers yes for is fulfilled from review on. :func:`outstanding` is that one answer, read by
the frontier, the lookahead and Run Agent's gate alike.

**A wait is no work, and it is done when it is over.** ``counts_as_work`` leaves a wait out
of every partition and count, and ``status_for`` — ``schedule.wait_status`` in the window
and the terminal — reads it done once its day has come, so what waits on it is ready then.

**A stored claim beats the graph.** A step marked done whose prerequisites are not is
honoured as done — the graph gates *launching*, not *recording* — so out-of-order
completion is never an error, and finishing a step frees its dependents no matter what
the rest of the graph says.

**An agent waiting on a person is on the board.** A step in progress whose agent asks for
somebody — a plan to approve, a question to answer — is handed in as ``asks_person`` and
lands in ``asking`` rather than ``running``: the work is not stuck on the graph, it is stuck
on a person, which is what a board of what needs a person is for.

**And work under review an agent takes on is not.** A step reading ready for review is a
person's turn unless an agent will take it from there — its review, a collector — through
a link that auto-progresses, and that agent is neither blocked nor done (:func:`taken`).
Such a step lands in ``taken`` rather than ``review``, off the board like running work, so
the board's *Ready for review* is exactly the steps the canvas pulses for.

**Some of the frontier is due.** :func:`due` is the part of it nobody needs to launch by
hand: an agent step whose last prerequisite was fulfilled *through* an auto-progress link —
a collector's sources, a review's subject, just reached review. A window that launches
what becomes due starts it; the terminal says it became due.

**Several projects are one board by merging theirs** (:func:`across`, :func:`merge`): edges
never cross a project, so each walk is unchanged, and the merge ranks what a person acts on
by unlocks again over the whole, ties going library order and then each project's own.

**Nothing here is written to disk**, for ``ordering.py``'s reason: a stored answer can
disagree with the statuses it came from the moment ``dplanner status set`` runs with no
window open to notice. The Step statuses tab, the Control Centre, ``dplanner progression
show`` and ``--json`` are readers of the functions below.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.planning.status import REVIEW_AND_MERGE, Status


def _all_work(_step: Step) -> bool:
    return True


def _never(_waiter: Step, _source: Step) -> bool:
    return False


def _answers_no(_step: Step) -> bool:
    return False


def outstanding(
    library: Library,
    waiter: Step,
    status_for: Callable[[Step], Status],
    auto_progresses: Callable[[Step, Step], bool] = _never,
) -> list[Step]:
    """The resolved prerequisites ``waiter`` still waits on — dead ids skipped, as everywhere.

    A prerequisite is fulfilled when it reads done, or when it reads ready for review or
    ready to merge across a link that auto-progresses: the step waiting on it takes the
    work from there.
    """
    waiting = []
    for source in library.requires(waiter.id):
        status = status_for(source)
        # The link is asked about only when its source reads a word the answer can change:
        # this runs for every link on every walk.
        if status is not Status.DONE and not (
            status in REVIEW_AND_MERGE and auto_progresses(waiter, source)
        ):
            waiting.append(source)
    return waiting


def due(
    library: Library,
    project: Project,
    status_for: Callable[[Step], Status],
    auto_progresses: Callable[[Step, Step], bool],
    is_agent: Callable[[Step], bool],
    running: Callable[[Step], bool] = _answers_no,
    counts_as_work: Callable[[Step], bool] = _all_work,
) -> list[Step]:
    """The agent steps auto-progress made due, in project order: nobody has started them, no
    agent runs in them, nothing they wait on is unfinished — and at least one of those
    prerequisites was fulfilled *through* an auto-progress link, reading ready for review or
    ready to merge.

    That last clause is the whole difference from Ready to start. A collector whose sources a
    person set done by hand is ready for a person to launch; one whose sources just reached
    review was made ready by the flag, and the flag's promise is that it starts on its own.
    ``running`` is whether an agent run is recorded on the step — the launch's own stamp,
    which is what keeps a step from being due twice.
    """
    found = []
    for step in project.steps:
        if not counts_as_work(step) or not is_agent(step) or running(step):
            continue
        if status_for(step) is not Status.PENDING:
            continue
        if outstanding(library, step, status_for, auto_progresses):
            continue
        if any(
            status_for(source) in REVIEW_AND_MERGE and auto_progresses(step, source)
            for source in library.requires(step.id)
        ):
            found.append(step)
    return found


def taken(
    library: Library,
    step: Step,
    status_for: Callable[[Step], Status],
    auto_progresses: Callable[[Step, Step], bool],
    is_agent: Callable[[Step], bool],
) -> bool:
    """Whether an agent takes ``step``'s work on from review: a step waiting on it across a
    link that auto-progresses — its review, a collector — that an agent works and that is
    neither blocked nor done. A step under review that none takes waits on a person.

    The one answer the board's *Ready for review* and the canvas's pulse both read.
    """
    return any(
        is_agent(waiter)
        and status_for(waiter) not in (Status.BLOCKED, Status.DONE)
        and auto_progresses(waiter, step)
        for waiter in library.dependents(step.id)
    )


@dataclass(frozen=True)
class Upcoming:
    """A step one move away: everything it waits on is on the board already.

    ``after`` is the not-done prerequisites it still waits on, in project order — steps
    that are running, blocked, under review, waiting on a merge or ready to start.
    """

    step: Step
    after: tuple[Step, ...]


@dataclass(frozen=True)
class Progression:
    """Every step in exactly one place: how far the project is, and what moves next.

    ``attention`` is the blocked steps — stuck on a person, not on the graph — kept
    apart from ``running`` because they are the rows that need eyes; ``asking`` is running
    work whose agent waits on a person, for the same reason; ``review`` and ``merge`` are
    finished work a person looks at next, and ``taken`` finished work an agent takes on
    from review (:func:`taken`). ``waiting`` is everything further
    than one move out; a step whose prerequisite is merely upcoming stays there, because
    the lookahead is deliberately one move and not a forecast.

    ``unlocks`` counts, for every step of work not done, the transitive dependents not yet
    done — the downstream weight finishing it feeds. It is what ranks each partition a
    person acts on (attention, review, merge, ready): all of one is valid, and this is
    what makes some of it urgent.
    """

    done: tuple[Step, ...]
    running: tuple[Step, ...]
    asking: tuple[Step, ...]
    review: tuple[Step, ...]
    taken: tuple[Step, ...]
    merge: tuple[Step, ...]
    attention: tuple[Step, ...]
    ready: tuple[Step, ...]
    upcoming: tuple[Upcoming, ...]
    waiting: tuple[Step, ...]
    unlocks: Mapping[StepId, int]

    @property
    def total(self) -> int:
        return (
            len(self.done)
            + len(self.running)
            + len(self.asking)
            + len(self.review)
            + len(self.taken)
            + len(self.merge)
            + len(self.attention)
            + len(self.ready)
            + len(self.upcoming)
            + len(self.waiting)
        )

    @property
    def percent(self) -> float:
        """How much of the project is done, by step count. 0.0 for an empty project.

        Steps are not equal sizes, but a count never lies about what it is —
        ``estimated_progress`` is the weighted companion for a project that carries
        estimates.
        """
        return 100.0 * len(self.done) / self.total if self.total else 0.0


def progression(
    library: Library,
    project: Project,
    status_for: Callable[[Step], Status],
    counts_as_work: Callable[[Step], bool] = _all_work,
    auto_progresses: Callable[[Step, Step], bool] = _never,
    asks_person: Callable[[Step], bool] = _answers_no,
    is_agent: Callable[[Step], bool] = _answers_no,
) -> Progression:
    """One walk in project order, so the answer is deterministic — ``ordering.py``'s rule.

    Each step lands in the first partition that claims it: a stored status first (done,
    blocked, in-progress, ready-for-review, ready-to-merge), then the graph
    (ready, upcoming, waiting). A blocked prerequisite still counts towards ``upcoming`` — it sits
    visibly on the board with a warning, and a step must not churn out of the queue when
    its prerequisite flips between in-progress and blocked. A step that is no work
    (``counts_as_work``) lands in none of them, but what it reads still gates what waits
    on it. Each partition a person acts on is ranked by ``unlocks``; ties keep project
    order. ``auto_progresses`` says which links free their waiter from review on
    (:func:`outstanding`); ``asks_person`` which steps in progress wait on a person
    (``asking``); ``is_agent`` which steps an agent works, so a step under review that one
    of them takes on is ``taken`` rather than a person's ``review``.
    """
    status = {step.id: status_for(step) for step in project.steps}
    work = [step for step in project.steps if counts_as_work(step)]
    # Claimed by a stored status and not done: on the board, one move from what waits on it.
    on_board = {Status.IN_PROGRESS, Status.BLOCKED, Status.READY_FOR_REVIEW, Status.READY_TO_MERGE}

    def claiming(wanted: Status) -> list[Step]:
        return [step for step in work if status[step.id] is wanted]

    pending = [step for step in work if status[step.id] not in {Status.DONE, *on_board}]

    def status_of(step: Step) -> Status:
        return status.get(step.id, Status.PENDING)

    def waits_on(step: Step) -> list[Step]:
        return outstanding(library, step, status_of, auto_progresses)

    frontier = [step for step in pending if not waits_on(step)]
    ready_ids = {step.id for step in frontier}
    # The reverse edges, built once: asking the library per visit would scan the project
    # for every step of every cone.
    dependents: dict[StepId, list[StepId]] = {step.id: [] for step in project.steps}
    for step in project.steps:
        for target in step.edges.get("requires", []):
            if target in dependents:
                dependents[target].append(step.id)
    counted = {step.id for step in work}
    unlocks = {
        step.id: _unlocks(dependents, step, status, counted)
        for step in work
        if status[step.id] != Status.DONE
    }

    def ranked(steps: list[Step]) -> tuple[Step, ...]:
        return _ranked(steps, unlocks)

    upcoming: list[Upcoming] = []
    waiting: list[Step] = []
    for step in pending:
        if step.id in ready_ids:
            continue
        after = waits_on(step)
        if all(status[t.id] in on_board or t.id in ready_ids for t in after):
            upcoming.append(Upcoming(step, tuple(after)))
        else:
            waiting.append(step)

    in_progress = claiming(Status.IN_PROGRESS)
    under_review = claiming(Status.READY_FOR_REVIEW)
    handed_on = {
        step.id
        for step in under_review
        if taken(library, step, status_of, auto_progresses, is_agent)
    }
    return Progression(
        done=tuple(claiming(Status.DONE)),
        running=tuple(step for step in in_progress if not asks_person(step)),
        asking=ranked([step for step in in_progress if asks_person(step)]),
        review=ranked([step for step in under_review if step.id not in handed_on]),
        taken=tuple(step for step in under_review if step.id in handed_on),
        merge=ranked(claiming(Status.READY_TO_MERGE)),
        attention=ranked(claiming(Status.BLOCKED)),
        ready=ranked(frontier),
        upcoming=tuple(upcoming),
        waiting=tuple(waiting),
        unlocks=unlocks,
    )


def _ranked(steps: Iterable[Step], unlocks: Mapping[StepId, int]) -> tuple[Step, ...]:
    """Most unlocked first; a stable sort, so ties keep the order they arrived in."""
    return tuple(sorted(steps, key=lambda step: -unlocks[step.id]))


def merge(found: Iterable[Progression]) -> Progression:
    """Several projects' progressions as one board, in the order they are handed in.

    Every partition a person acts on is ranked by unlocks again over the whole, and the sort
    is stable — so handed in library order, ties go to the earlier project and then to that
    project's own rank. The rest keep their order, project after project. Step ids are
    unique across a library, so the unlock counts join without colliding, and one
    progression merged is itself.
    """
    each = tuple(found)
    unlocks = {step_id: count for one in each for step_id, count in one.unlocks.items()}

    def joined[T](partition: Callable[[Progression], tuple[T, ...]]) -> tuple[T, ...]:
        return tuple(item for one in each for item in partition(one))

    return Progression(
        done=joined(lambda one: one.done),
        running=joined(lambda one: one.running),
        asking=_ranked(joined(lambda one: one.asking), unlocks),
        review=_ranked(joined(lambda one: one.review), unlocks),
        taken=joined(lambda one: one.taken),
        merge=_ranked(joined(lambda one: one.merge), unlocks),
        attention=_ranked(joined(lambda one: one.attention), unlocks),
        ready=_ranked(joined(lambda one: one.ready), unlocks),
        upcoming=joined(lambda one: one.upcoming),
        waiting=joined(lambda one: one.waiting),
        unlocks=unlocks,
    )


def across(
    library: Library,
    projects: Sequence[Project],
    status_for: Callable[[Step], Status],
    counts_as_work: Callable[[Step], bool] = _all_work,
    auto_progresses: Callable[[Step, Step], bool] = _never,
    asks_person: Callable[[Step], bool] = _answers_no,
    is_agent: Callable[[Step], bool] = _answers_no,
) -> Progression:
    """Every project's progression merged into one board — what can start anywhere.

    Hand ``projects`` in library order: that is the order ties are settled in. Edges never
    cross a project, so each walk is the one-project walk unchanged.
    """
    return merge(
        progression(
            library, project, status_for, counts_as_work, auto_progresses, asks_person, is_agent
        )
        for project in projects
    )


def _unlocks(
    dependents: dict[StepId, list[StepId]],
    step: Step,
    status: dict[StepId, Status],
    counted: set[StepId],
) -> int:
    """How many not-done steps of work transitively wait on ``step``.

    A depth-first walk over the reverse edges; the visited set is also the cycle guard,
    the same defensive stance ``ordering.depths()`` takes against a hand-edited file. A
    done dependent is walked through but not counted — its own dependents still wait on
    this step through the graph.
    """
    seen: set[StepId] = set()

    def visit(step_id: StepId) -> None:
        for dependent in dependents.get(step_id, ()):
            if dependent in seen:
                continue
            seen.add(dependent)
            visit(dependent)

    visit(step.id)
    return sum(1 for found in seen if found in counted and status.get(found) != Status.DONE)


def estimated_progress(
    progress: Progression,
    days_for: Callable[[Step], float | None],
) -> tuple[float, float] | None:
    """(done days, total estimated days), or ``None`` when nothing carries an estimate.

    The weighted companion to ``percent`` — same injection seam as ``schedule()``, so
    the domain still never learns what an estimate is stored as. Unestimated steps
    contribute nothing to either number; the honest reading is "of the work somebody
    sized, this much is finished".
    """
    everything: Iterable[Step] = (
        *progress.done,
        *progress.running,
        *progress.asking,
        *progress.review,
        *progress.taken,
        *progress.merge,
        *progress.attention,
        *progress.ready,
        *(coming.step for coming in progress.upcoming),
        *progress.waiting,
    )
    estimated = [(step, days) for step in everything if (days := days_for(step)) is not None]
    if not estimated:
        return None
    done_ids = {step.id for step in progress.done}
    finished = sum(days for step, days in estimated if step.id in done_ids)
    return finished, sum(days for _step, days in estimated)
