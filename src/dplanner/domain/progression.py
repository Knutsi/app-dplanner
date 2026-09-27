"""What can be launched right now, given the graph and what status claims are stored.

``ordering.py`` answers "in what order *could* this be done"; this answers "and where are
we". It is a different question from wave membership: a step deep in the graph whose
prerequisites have all been finished is launchable today, and no wave number says so. The
frontier here is a per-step check — every ``requires`` target reads done — not wave one,
and the two only coincide in a project where nothing has been finished yet.

**The domain never learns what a status is stored as.** ``status_for`` is a function the
caller supplies, exactly the seam ``schedule.py`` uses for ``days_for``: the module that
owns the status aspect owns its schema, and this file works for any other source of
status somebody wires in later. The words this walk understands are ``done``,
``in-progress``, ``ready-for-review``, ``ready-to-merge`` and ``blocked`` — the status
aspect stores exactly these, importing them from here; anything else — including whatever
a wilder function returns — reads as pending, because a derivation must not crash on a
claim it does not recognise.

**Review and merge are on the board, and not done.** A step whose agent has finished waits
for a person (``ready-for-review``) or for its merge (``ready-to-merge``): it is claimed out
of the graph like a running step, counts as one move away for the lookahead, and frees
nothing — a plain ``requires`` is fulfilled by ``done`` alone, so nothing starts on work
nobody has accepted.

**A wait is no work, and it is done when it is over.** ``counts_as_work`` leaves a wait out
of every partition and count, and ``status_for`` — ``schedule.wait_status`` in the window
and the terminal — reads it done once its day has come, so what waits on it is ready then.

**A stored claim beats the graph.** A step marked done whose prerequisites are not is
honoured as done — the graph gates *launching*, not *recording* — so out-of-order
completion is never an error, and finishing a step frees its dependents no matter what
the rest of the graph says.

**Nothing here is written to disk**, for ``ordering.py``'s reason: a stored answer can
disagree with the statuses it came from the moment ``dplanner status set`` runs with no
window open to notice. The tab, ``dplanner progression show`` and ``--json`` are three
readers of the one function below.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from dplanner.domain.model import Library, Project, Step, StepId

DONE = "done"
IN_PROGRESS = "in-progress"
# The agent's work is finished and a person — or a reviewing agent — looks next.
READY_FOR_REVIEW = "ready-for-review"
# Accepted, and waiting on its merge.
READY_TO_MERGE = "ready-to-merge"
# Finished work handed to a person — its review, then its merge: past in progress, not done.
HANDED_OFF = (READY_FOR_REVIEW, READY_TO_MERGE)
BLOCKED = "blocked"
# A wait that is not over yet — a derived reading (``schedule.wait_status``), never stored.
WAITING = "waiting"


def phrase(status: str) -> str:
    """A status word as running text shows it: its hyphens as spaces (*ready for review*)."""
    return status.replace("-", " ")


def _all_work(_step: Step) -> bool:
    return True


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
    apart from ``running`` because they are the rows that need eyes; ``review`` and
    ``merge`` are finished work a person looks at next. ``waiting`` is everything further
    than one move out; a step whose prerequisite is merely upcoming stays there, because
    the lookahead is deliberately one move and not a forecast.

    ``unlocks`` counts, for every step of work not done, the transitive dependents not yet
    done — the downstream weight finishing it feeds. It is what ranks each partition a
    person acts on (attention, review, merge, ready): all of one is valid, and this is
    what makes some of it urgent.
    """

    done: tuple[Step, ...]
    running: tuple[Step, ...]
    review: tuple[Step, ...]
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
            + len(self.review)
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
    status_for: Callable[[Step], str],
    counts_as_work: Callable[[Step], bool] = _all_work,
) -> Progression:
    """One walk in project order, so the answer is deterministic — ``ordering.py``'s rule.

    Each step lands in the first partition that claims it: a stored status first
    (done, blocked, in-progress, ready-for-review, ready-to-merge), then the graph (ready,
    upcoming, waiting). A blocked prerequisite still counts towards ``upcoming`` — it sits
    visibly on the board with a warning, and a step must not churn out of the queue when
    its prerequisite flips between in-progress and blocked. A step that is no work
    (``counts_as_work``) lands in none of them, but what it reads still gates what waits
    on it. Each partition a person acts on is ranked by ``unlocks``; ties keep project
    order.
    """
    status = {step.id: status_for(step) for step in project.steps}
    work = [step for step in project.steps if counts_as_work(step)]
    # Claimed by a stored status and not done: on the board, one move from what waits on it.
    on_board = {IN_PROGRESS, BLOCKED, READY_FOR_REVIEW, READY_TO_MERGE}

    def claiming(word: str) -> list[Step]:
        return [step for step in work if status[step.id] == word]

    pending = [step for step in work if status[step.id] not in {DONE, *on_board}]

    def outstanding(step: Step) -> list[Step]:
        """The resolved prerequisites not yet done — dead ids skipped, as everywhere."""
        return [t for t in library.requires(step.id) if status.get(t.id) != DONE]

    frontier = [step for step in pending if not outstanding(step)]
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
        if status[step.id] != DONE
    }

    def ranked(steps: list[Step]) -> tuple[Step, ...]:
        return tuple(sorted(steps, key=lambda step: -unlocks[step.id]))  # Stable.

    upcoming: list[Upcoming] = []
    waiting: list[Step] = []
    for step in pending:
        if step.id in ready_ids:
            continue
        waits_on = outstanding(step)
        if all(status[t.id] in on_board or t.id in ready_ids for t in waits_on):
            upcoming.append(Upcoming(step, tuple(waits_on)))
        else:
            waiting.append(step)

    return Progression(
        done=tuple(claiming(DONE)),
        running=tuple(claiming(IN_PROGRESS)),
        review=ranked(claiming(READY_FOR_REVIEW)),
        merge=ranked(claiming(READY_TO_MERGE)),
        attention=ranked(claiming(BLOCKED)),
        ready=ranked(frontier),
        upcoming=tuple(upcoming),
        waiting=tuple(waiting),
        unlocks=unlocks,
    )


def _unlocks(
    dependents: dict[StepId, list[StepId]],
    step: Step,
    status: dict[StepId, str],
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
    return sum(1 for found in seen if found in counted and status.get(found) != DONE)


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
        *progress.review,
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
