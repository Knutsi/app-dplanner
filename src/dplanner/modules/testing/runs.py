"""Test runs: one occasion of executing a scope, and what each test did.

A run lives beside the *project*, not beside a step, because it spans steps — the same
namespace as the tests themselves, one ``ModuleDataFormat`` over two shapes, which is the
arrangement ``estimation`` already uses for a step's days and a project's start date.

Three rules earn their own paragraph:

**A run freezes its membership at start.** ``tests`` is the list of ids the run was opened
over, not a live query, so a closed run cannot quietly change meaning when somebody adds a
test or relinks the graph afterwards. A run is a record of an occasion.

**A missing result is pending.** Absence encodes the default here as everywhere, so opening
a run over two hundred tests writes two hundred *ids* and no statuses, and the file grows
only as the work is actually done.

**At most one run is open per project.** That is what lets "mark this test failed" be a pure
function of the context — there is no hidden "which run" the user has to have selected, and
no verb has to carry one. Starting a run closes whatever was open.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final

from dplanner.core.module_data import stamped
from dplanner.domain.model import Project, StepId, now_stamp
from dplanner.modules.testing.aspect import DATA_FORMAT, next_numbered

# In the order a run moves through them. "pending" first because it is the default, and it
# is the one that is never written: a test with no result entry is pending.
STATUSES: Final = ("pending", "ok", "failed", "skipped")
PENDING: Final = "pending"

# R100, R101, … — the same shape as a test id, so the two never read as one vocabulary
# with two spellings. A run's *name* is its label; this is what a verb takes.
RUN_ID_PREFIX = "R"
FIRST_RUN_NUMBER = 100


@dataclass(frozen=True)
class Result:
    status: str
    note: str = ""


@dataclass(frozen=True)
class Run:
    """One occasion of executing a scope. ``closed`` empty means the run is still open."""

    id: str
    label: str = ""
    opened: str = ""
    closed: str = ""
    scope: StepId = ""
    tests: tuple[str, ...] = ()
    results: dict[str, Result] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return not self.closed

    def result(self, test_id: str) -> Result:
        """What ``test_id`` did in this run. A test with no entry is pending."""
        return self.results.get(test_id, Result(PENDING))


def read(project: Project) -> list[Run]:
    """The project's runs, oldest first. Unreadable entries read as absent."""
    raw = project.module_data.get(DATA_FORMAT.module_id, {}).get("runs")
    if not isinstance(raw, list):
        return []
    return [
        Run(
            id=entry["id"],
            label=str(entry.get("label", "")),
            opened=str(entry.get("opened", "")),
            closed=str(entry.get("closed", "")),
            scope=str(entry.get("scope", "")),
            tests=tuple(t for t in entry.get("tests", []) if isinstance(t, str)),
            results=_results(entry.get("results")),
        )
        for entry in raw
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    ]


def _results(value: Any) -> dict[str, Result]:
    if not isinstance(value, dict):
        return {}
    found = {}
    for test_id, entry in value.items():
        if not isinstance(test_id, str) or not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if status not in STATUSES or status == PENDING:
            continue  # An unknown word, or a written-out default, reads as pending.
        found[test_id] = Result(status, str(entry.get("note", "")))
    return found


def write(runs: Sequence[Run]) -> dict[str, Any]:
    """The project entry to store. No runs gives ``{}``, which removes the file."""
    if not runs:
        return {}
    return stamped(
        {
            "runs": [
                {
                    "id": run.id,
                    **({"label": run.label} if run.label else {}),
                    **({"opened": run.opened} if run.opened else {}),
                    **({"closed": run.closed} if run.closed else {}),
                    **({"scope": run.scope} if run.scope else {}),
                    **({"tests": list(run.tests)} if run.tests else {}),
                    **(
                        {
                            "results": {
                                test_id: {
                                    "status": result.status,
                                    **({"note": result.note} if result.note else {}),
                                }
                                for test_id, result in sorted(run.results.items())
                            }
                        }
                        if run.results
                        else {}
                    ),
                }
                for run in runs
            ]
        },
        DATA_FORMAT.version,
    )


def open_run(runs: Sequence[Run]) -> Run | None:
    """The one run still open, or ``None``. Later wins, defensively, if a file has two."""
    return next((run for run in reversed(runs) if run.is_open), None)


def find(runs: Sequence[Run], run_id: str) -> Run | None:
    return next((run for run in runs if run.id == run_id), None)


def next_run_id(runs: Sequence[Run]) -> str:
    """The next free ``RN``, minted the same way a test id is."""
    return next_numbered((run.id for run in runs), RUN_ID_PREFIX, FIRST_RUN_NUMBER)


def started(
    runs: Sequence[Run],
    test_ids: Sequence[str],
    *,
    label: str = "",
    scope: StepId = "",
) -> list[Run]:
    """``runs`` with whatever was open closed, and a new run over ``test_ids`` appended."""
    stamp = now_stamp()
    closed = [run if not run.is_open else replace(run, closed=stamp) for run in runs]
    return [
        *closed,
        Run(
            id=next_run_id(runs),
            label=label,
            opened=stamp,
            scope=scope,
            tests=tuple(test_ids),
        ),
    ]


def marked(run: Run, test_id: str, status: str, note: str = "") -> Run:
    """``run`` with one test's result set. ``pending`` removes the entry — absence is it."""
    if status not in STATUSES:
        raise ValueError(f"unknown test result {status!r} (one of {', '.join(STATUSES)})")
    results = dict(run.results)
    if status == PENDING:
        results.pop(test_id, None)
    else:
        results[test_id] = Result(status, note)
    return replace(run, results=results)


def closed(run: Run) -> Run:
    """``run`` stamped closed. Closing an already-closed run leaves it exactly as it was."""
    return run if run.closed else replace(run, closed=now_stamp())


def replaced(runs: Sequence[Run], run: Run) -> list[Run]:
    return [run if existing.id == run.id else existing for existing in runs]


@dataclass(frozen=True)
class Outcome:
    """How a test last did: the result, and the run that recorded it."""

    run: Run
    result: Result


def latest(runs: Sequence[Run], test_id: str) -> Outcome | None:
    """The newest run that actually recorded something for ``test_id``.

    Newest *with a result*, not simply newest: a test that was not in yesterday's run has no
    answer from it, and reporting "pending" there would erase what last week established.
    """
    for run in reversed(runs):
        result = run.results.get(test_id)
        if result is not None:
            return Outcome(run, result)
    return None


def latest_results(runs: Sequence[Run]) -> dict[str, Outcome]:
    """Every test's last recorded outcome, by test id — one pass over the runs."""
    found: dict[str, Outcome] = {}
    for run in runs:
        for test_id, result in run.results.items():
            found[test_id] = Outcome(run, result)
    return found


def tally(statuses: Sequence[str]) -> dict[str, int]:
    """How many of each status, every word present so a reader never has to guess a zero."""
    counts = dict.fromkeys(STATUSES, 0)
    for status in statuses:
        counts[status if status in counts else PENDING] += 1
    return counts
