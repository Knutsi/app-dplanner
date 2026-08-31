"""The test aspect: what a step must keep passing, long after the step is done.

A description says what a step *is*; a test says how you would *prove* it, and — unlike an
acceptance criterion, which is consumed when the work closes — it outlives the step and gets
run again. That difference is the whole reason this is an aspect of its own rather than a
paragraph in the description.

**A step carries several tests, and each is its own record.** A test is not a node: it
belongs to exactly one step, never appears on the canvas, and the graph knows nothing about
it. What it is *not* is a second graph — the step is the addressable thing, and a test hangs
off it the way an estimate does.

**The body is a markdown string inside the record.** A node holds exactly one prose document
(``FORMAT.md``), and a step carries N tests, so the one-document rule does not stretch to
them; the nearest existing shape is ``spec``'s requirement records, and this follows it. The
cost is that a body edit diffs as one changed JSON line rather than line by line — bearable
because a test body is a few lines. Images are the exception and go where a description's
images go: the step's file area, referenced as ``![](assets/…)``.

Ids are minted per *project*, not per step, so a run's results map is flat and a person can
say "t7 failed" out loud. ``spec``'s ``next_id`` is the precedent.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.scope import StepPredicate, cone

MODULE_ID = "testing"
DATA_FORMAT = ModuleDataFormat(MODULE_ID)

# Ids people say out loud and write in a bug report: T100, T101, … Three digits from
# the start so every id in a project is the same width, and high enough that nobody
# mistakes one for a count of anything.
TEST_ID_PREFIX = "T"
FIRST_TEST_NUMBER = 100


@dataclass(frozen=True)
class Test:
    """One thing a step must keep doing. ``body`` is markdown; ``id`` is project-unique."""

    # pytest collects any class called Test*, and this one is imported by name into the
    # suite. The domain word is "test"; the opt-out is cheaper than a worse name.
    __test__ = False

    id: str
    title: str
    body: str = ""
    archived: bool = False


def read(step: Step) -> list[Test]:
    """The step's tests in order. Unreadable entries read as absent, never as an error."""
    raw = step.module_data.get(MODULE_ID, {}).get("tests")
    if not isinstance(raw, list):
        return []
    return [
        Test(
            id=entry["id"],
            title=str(entry.get("title", "")),
            body=str(entry.get("body", "")),
            archived=bool(entry.get("archived")),
        )
        for entry in raw
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    ]


def write(tests: Sequence[Test]) -> dict[str, Any]:
    """The entry to store. No tests gives ``{}``, which removes the file."""
    if not tests:
        return {}
    return stamped(
        {
            "tests": [
                {
                    "id": test.id,
                    "title": test.title,
                    **({"body": test.body} if test.body else {}),
                    **({"archived": True} if test.archived else {}),
                }
                for test in tests
            ]
        },
        DATA_FORMAT.version,
    )


def enabled(step: Step) -> bool:
    """Whether the step carries the aspect. The list is the marker; there is no "on" key."""
    return bool(read(step))


def find(tests: Sequence[Test], test_id: str) -> Test | None:
    return next((test for test in tests if test.id == test_id), None)


def replace(tests: Sequence[Test], test: Test) -> list[Test]:
    """``tests`` with the record of the same id swapped out, keeping its position."""
    return [test if existing.id == test.id else existing for existing in tests]


def summary(step: Step) -> str:
    """One short phrase for a step's row, or "" when there is nothing to say."""
    live = [test for test in read(step) if not test.archived]
    if not live:
        return ""
    return "1 test" if len(live) == 1 else f"{len(live)} tests"


def project_tests(project: Project, *, archived: bool = False) -> list[tuple[Step, Test]]:
    """Every test in the project, in step order then test order.

    ``archived`` says whether to include the ones taken off the roster; the default is the
    roster itself, because that is what every reader but the archive filter wants.
    """
    return [
        (step, test)
        for step in project.steps
        for test in read(step)
        if archived or not test.archived
    ]


def next_numbered(existing: Iterable[str], prefix: str, start: int) -> str:
    """The next free ``<prefix>N``, counting from ``start`` when there is nothing yet.

    Ids a person can say out loud and an agent can guess the shape of. Tests and runs both
    mint ids this way, and so does ``spec`` for its requirements; that third copy lives in a
    module this one may not import, and is left alone rather than dragged into a feature
    change.
    """
    numbers = [
        int(entry[len(prefix) :])
        for entry in existing
        if entry.startswith(prefix) and entry[len(prefix) :].isdigit()
    ]
    return f"{prefix}{max(numbers) + 1 if numbers else start}"


def next_test_id(project: Project) -> str:
    """The next free ``tN`` across the whole project, archived tests included."""
    return next_numbered(
        (test.id for _step, test in project_tests(project, archived=True)),
        TEST_ID_PREFIX,
        FIRST_TEST_NUMBER,
    )


def mint_ids(project: Project, count: int) -> list[str]:
    """``count`` free ids at once, for a verb that adds more than one test in a run."""
    first = int(next_test_id(project)[len(TEST_ID_PREFIX) :])
    return [f"{TEST_ID_PREFIX}{first + offset}" for offset in range(count)]


def covered(
    library: Library,
    project: Project,
    step_id: StepId,
    *,
    archived: bool = False,
    stops_at: StepPredicate | None = None,
) -> list[tuple[Step, Test]]:
    """The tests at and behind ``step_id`` — what a collector stands for.

    One walk, many readers: the *Covers* tab, the Tests tab's scope selector,
    ``dplanner scope show`` and ``test-run start --scope``. A check, a feature and a
    milestone are the same computation asked with a different ``stops_at`` — a check stops
    at nothing and stands for the whole cone behind it, a feature stops at the previous
    feature and owns only what is new. ``None`` is the untruncated case.
    """
    scope = project.step(step_id)
    found = cone(library, project, step_id, stops_at=stops_at)
    reach = [*found.steps, *([scope] if scope is not None else [])]
    ordered = {step.id: step for step in reach}
    return [
        (step, test)
        for step in project.steps
        if step.id in ordered
        for test in read(step)
        if archived or not test.archived
    ]


# Last, because it names the pieces above: the one declaration everything reads.
SPEC = AspectSpec(
    id=MODULE_ID,
    label="Test",
    summary=(
        "What a step must keep passing: acceptance criteria that outlive the work. A step "
        "carries several, each with its own result in a test run."
    ),
    data_format=DATA_FORMAT,
    phrase=summary,
)
