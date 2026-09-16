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

**A test also says who it is for** — a closed list of :data:`AUDIENCES`, owned here rather
than by the composition root because nothing outside testing has an opinion about the word.
A test may carry several; one that carries none reads as ``other`` through
:func:`audiences_of`, which is what let the field arrive without migrating anybody's plan.
``project lint`` asks for the explicit answer instead, a test at a time.
"""

import dataclasses
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from dplanner.cli.command import CliError
from dplanner.core.module_data import ModuleDataFormat, stamped
from dplanner.domain.aspects import AspectSpec
from dplanner.domain.assets import (
    AssetLocation,
    AssetSource,
    AssetUse,
    area_assets,
    asset_references,
)
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.scope import StepPredicate, cone
from dplanner.domain.store import FilesFor

MODULE_ID = "testing"


def _to_format_2(data: dict[str, Any]) -> dict[str, Any]:
    """Format 1 shapes are valid format 2 shapes: the bump exists for the ``audiences`` key.

    Beside a step this entry is a step's tests and beside the project it is the project's
    runs — one module id, two shapes, and a migration owes both a thought (``FORMAT.md``).
    Neither shape changed, so both pass through.

    What the stamp buys is narrower than it looks, and the two existing pass-throughs
    overstate it: :func:`~dplanner.core.module_data.migrated` only makes the *migration
    pass* leave newer data alone with a warning. ``set_module_data`` checks no version and
    :func:`read` never looks at the stamp, so an older build still reads these tests and
    still rewrites them without their audiences. The stamp records that the entry may carry
    keys an older build does not know; it does not enforce it.
    """
    return dict(data)


DATA_FORMAT = ModuleDataFormat(MODULE_ID, 2, (_to_format_2,))

# Ids people say out loud and write in a bug report: T100, T101, … Three digits from
# the start so every id in a project is the same width, and high enough that nobody
# mistakes one for a count of anything.
TEST_ID_PREFIX = "T"
FIRST_TEST_NUMBER = 100


@dataclass(frozen=True)
class Audience:
    """Somebody a test is written for. Closed list, owned here — see :data:`AUDIENCES`."""

    id: str
    label: str
    meaning: str  # One line, printed wherever the list is offered.


# Who a test is for. Closed, and owned by this module rather than the composition root,
# because nothing outside testing has an opinion about the word — the tab, the verbs and
# the report all read this tuple directly. Widening it is a line here and nothing else.
AUDIENCES: Final[tuple[Audience, ...]] = (
    Audience("qa", "QA", "Somebody executing the test by hand"),
    Audience("technical", "Technical", "An engineer proving the mechanism works"),
    Audience("other", "Other", "Neither of those — or nobody has said yet"),
)
AUDIENCE_IDS = tuple(audience.id for audience in AUDIENCES)
# What a test with nothing stored reads as. A project written before audiences existed is
# not wrong, it is unclassified, and unclassified work is somebody's — `lint` asks for the
# explicit answer (`test.audience`) rather than a migration guessing one.
DEFAULT_AUDIENCE = "other"


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
    # Who it is written for, in AUDIENCES order. Empty is *nobody has said*, which reads as
    # `other` through `audiences_of` and is what `lint`'s `test.audience` asks about.
    audiences: tuple[str, ...] = ()


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
            audiences=_audiences_in(entry.get("audiences")),
        )
        for entry in raw
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    ]


def _entry(test: Test) -> dict[str, Any]:
    """One test as it is stored. Absence encodes every default (``FORMAT.md``), and the
    audiences are re-ordered on the way out so the bytes never depend on the order somebody
    happened to name them in."""
    audiences = _audiences_in(list(test.audiences))
    return {
        "id": test.id,
        "title": test.title,
        **({"body": test.body} if test.body else {}),
        **({"archived": True} if test.archived else {}),
        **({"audiences": list(audiences)} if audiences else {}),
    }


def write(tests: Sequence[Test]) -> dict[str, Any]:
    """The entry to store. No tests gives ``{}``, which removes the file."""
    if not tests:
        return {}
    return stamped({"tests": [_entry(test) for test in tests]}, DATA_FORMAT.version)


def _audiences_in(raw: object) -> tuple[str, ...]:
    """The audiences a stored entry names: known ids only, in :data:`AUDIENCES` order.

    Normalising on the way in is what makes the order canonical everywhere — two agents
    naming the same pair in different orders write the same bytes, and a diff means
    something. An id this build does not know is dropped rather than raising, the same
    tolerance ``read`` shows the rest of the entry.
    """
    named = {entry for entry in raw if isinstance(entry, str)} if isinstance(raw, list) else set()
    return tuple(audience.id for audience in AUDIENCES if audience.id in named)


def audiences_of(test: Test) -> tuple[str, ...]:
    """What the test counts as: what it stored, or :data:`DEFAULT_AUDIENCE` when it stored
    nothing.

    The one derivation every view, filter and export reads, so an unclassified test lands
    somewhere honest instead of falling out of every list. Two readers deliberately ask the
    raw ``test.audiences`` instead — ``lint`` and the step panel's checkboxes — because
    theirs is the other question: *has anybody actually said?*
    """
    return test.audiences or (DEFAULT_AUDIENCE,)


def audience_words(test: Test) -> str:
    """What a row or a cell says a test is for: the labels, in order."""
    wanted = audiences_of(test)
    return ", ".join(audience.label for audience in AUDIENCES if audience.id in wanted)


def check_audience(audience_id: str) -> str:
    """``audience_id`` if it is one of :data:`AUDIENCES`; a CliError naming them otherwise."""
    if audience_id not in AUDIENCE_IDS:
        offered = ", ".join(f"{a.id} ({a.meaning.lower()})" for a in AUDIENCES)
        raise CliError(f"no such audience {audience_id!r} — one of: {offered}")
    return audience_id


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


def asset_source() -> AssetSource:
    """This aspect's slice of the project's asset catalog.

    Images live beside the *step* (the module docstring's rule) and are used while any of
    the step's test bodies links to them — archived tests included, because a test taken
    off the roster still owns its evidence.
    """

    def scan(_library: Library, project: Project, files: FilesFor) -> Sequence[AssetLocation]:
        locations: list[AssetLocation] = []
        for step in project.steps:
            names = area_assets(files, step.id, MODULE_ID)
            if not names:
                continue
            referencing = [(test, set(asset_references(test.body))) for test in read(step)]
            locations += [
                AssetLocation(
                    node_id=step.id,
                    module_id=MODULE_ID,
                    name=name,
                    uses=tuple(
                        AssetUse("step", step.id, step.title, f"test {test.id} — {test.title}")
                        for test, referenced in referencing
                        if name in referenced
                    ),
                )
                for name in names
            ]
        return locations

    return AssetSource(id=MODULE_ID, label="Tests", scan=scan)


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


def remint_for_paste(project: Project, steps: Sequence[Step]) -> None:
    """A copied step's tests get fresh ids — the paste policy this module hands in.

    An id is minted per project, so a copy that kept ``T100`` would make "T100 failed" name
    two tests; and a paste after a cut must not inherit the removed test's run history under
    the old id either. Minted across the whole batch at once, because the clones are not in
    the project yet and would otherwise all be offered the same next number.
    """
    carrying = [(step, read(step)) for step in steps if read(step)]
    fresh = iter(mint_ids(project, sum(len(tests) for _step, tests in carrying)))
    for step, tests in carrying:
        step.module_data[MODULE_ID] = write(
            [dataclasses.replace(test, id=next(fresh)) for test in tests]
        )


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
