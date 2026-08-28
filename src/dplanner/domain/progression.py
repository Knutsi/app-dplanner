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
``in-progress`` and ``blocked``; anything else — including whatever a wilder function
returns — reads as pending, because a derivation must not crash on a claim it does not
recognise.

**A stored claim beats the graph.** A step marked done whose prerequisites are not is
honoured as done — the graph gates *launching*, not *recording* — so out-of-order
completion is never an error, and finishing a step frees its dependents no matter what
the rest of the graph says.

**Nothing here is written to disk**, for ``ordering.py``'s reason: a stored answer can
disagree with the statuses it came from the moment ``dplanner status set`` runs with no
window open to notice. The tab, ``dplanner progression show`` and ``--json`` are three
readers of the one function below.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from dplanner.domain.model import Product, Project, Step, StepId

DONE = "done"
IN_PROGRESS = "in-progress"
BLOCKED = "blocked"


@dataclass(frozen=True)
class Launchable:
    """A step that can be started now, and what starting it is worth.

    ``unlocks`` counts the transitive dependents not yet done — the downstream weight
    that finishing this step feeds. It is what ranks the frontier: all of it is valid,
    this is what makes some of it urgent.
    """

    step: Step
    unlocks: int


@dataclass(frozen=True)
class Upcoming:
    """A step one move away: everything it waits on is on the board already.

    ``after`` is the not-done prerequisites it still waits on, in project order — the
    steps a reader can point at in the running and ready columns.
    """

    step: Step
    after: tuple[Step, ...]


@dataclass(frozen=True)
class Progression:
    """Every step in exactly one place: how far the project is, and what moves next.

    ``attention`` is the blocked steps — stuck on a person, not on the graph — kept
    apart from ``running`` because they are the rows that need eyes. ``waiting`` is
    everything further than one move out; a step whose prerequisite is merely upcoming
    stays here, because the lookahead is deliberately one move and not a forecast.
    """

    done: tuple[Step, ...]
    running: tuple[Step, ...]
    attention: tuple[Step, ...]
    ready: tuple[Launchable, ...]
    upcoming: tuple[Upcoming, ...]
    waiting: tuple[Step, ...]

    @property
    def total(self) -> int:
        return (
            len(self.done)
            + len(self.running)
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
    product: Product,
    project: Project,
    status_for: Callable[[Step], str],
) -> Progression:
    """One walk in project order, so the answer is deterministic — ``ordering.py``'s rule.

    Each step lands in the first partition that claims it: a stored status first
    (done, blocked, in-progress), then the graph (ready, upcoming, waiting). A blocked
    prerequisite still counts towards ``upcoming`` — it sits visibly on the board with a
    warning, and a step must not churn out of the queue when its prerequisite flips
    between in-progress and blocked.
    """
    status = {step.id: status_for(step) for step in project.steps}

    done = tuple(step for step in project.steps if status[step.id] == DONE)
    attention = tuple(step for step in project.steps if status[step.id] == BLOCKED)
    running = tuple(step for step in project.steps if status[step.id] == IN_PROGRESS)
    pending = [
        step for step in project.steps if status[step.id] not in (DONE, BLOCKED, IN_PROGRESS)
    ]

    def outstanding(step: Step) -> list[Step]:
        """The resolved prerequisites not yet done — dead ids skipped, as everywhere."""
        return [t for t in product.requires(step.id) if status.get(t.id) != DONE]

    frontier = [step for step in pending if not outstanding(step)]
    ready_ids = {step.id for step in frontier}
    ready = tuple(
        sorted(
            (Launchable(step, _unlocks(product, project, step, status)) for step in frontier),
            key=lambda launchable: -launchable.unlocks,  # Stable: ties keep project order.
        )
    )

    on_board = {IN_PROGRESS, BLOCKED}
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
        done=done,
        running=running,
        attention=attention,
        ready=ready,
        upcoming=tuple(upcoming),
        waiting=tuple(waiting),
    )


def _unlocks(
    product: Product,
    project: Project,
    step: Step,
    status: dict[StepId, str],
) -> int:
    """How many not-done steps transitively wait on ``step``.

    A depth-first walk over the reverse edges; the visited set is also the cycle guard,
    the same defensive stance ``ordering.depths()`` takes against a hand-edited file. A
    done dependent is walked through but not counted — its own dependents still wait on
    this step through the graph.
    """
    seen: set[StepId] = set()

    def visit(step_id: StepId) -> None:
        for dependent in product.dependents(step_id):
            if dependent.id in seen or project.step(dependent.id) is None:
                continue
            seen.add(dependent.id)
            visit(dependent.id)

    visit(step.id)
    return sum(1 for found in seen if status.get(found) != DONE)


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
        *progress.attention,
        *(launchable.step for launchable in progress.ready),
        *(coming.step for coming in progress.upcoming),
        *progress.waiting,
    )
    estimated = [(step, days) for step in everything if (days := days_for(step)) is not None]
    if not estimated:
        return None
    done_ids = {step.id for step in progress.done}
    finished = sum(days for step, days in estimated if step.id in done_ids)
    return finished, sum(days for _step, days in estimated)
