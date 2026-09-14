"""The test aspect: what a step must keep passing, long after the step is done.

A description says what a step *is*; a test says how you would *prove* it, and — unlike an
acceptance criterion, which is consumed when the work closes — it outlives the step and gets
run again. That difference is the whole reason this is an aspect of its own rather than a
paragraph in the description.

**A step carries several tests, and each is its own record.** A test is not a node: it
belongs to exactly one step, never appears on the canvas, and the graph knows nothing about
it. What it is *not* is a second graph — the step is the addressable thing, and a test hangs
off it the way an estimate does.

**A test says where it came from.** Every test carries at least one :class:`TestSource` —
a passage of a specification, or an implementation note — because a test nobody can trace
back to a claim about the product is a test nobody can judge: the tester cannot tell what
it is really asking, and the next planner cannot tell whether it still applies when the
spec moves. It is a `sources` list on the record rather than a single field, because one
test often proves two paragraphs, and it is *not* refused at write time: an existing plan
has thousands of tests that predate it, and a verb that refused them would strand the
plan rather than improve it. `dplanner project lint` names the ones with none
(`test.unsourced`), which is the same trade every other "ought to" in this application
makes.

**The body is a markdown string inside the record.** A node holds exactly one prose document
(``FORMAT.md``), and a step carries N tests, so the one-document rule does not stretch to
them; the nearest existing shape is ``spec``'s requirement records, and this follows it. The
cost is that a body edit diffs as one changed JSON line rather than line by line — bearable
because a test body is a few lines. Images are the exception and go where a description's
images go: the step's file area, referenced as ``![](assets/…)``.

Ids are minted per *project*, not per step, so a run's results map is flat and a person can
say "t7 failed" out loud. ``spec``'s ``next_id`` is the precedent.
"""

import dataclasses
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

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
    """A test may say where it came from; one that predates the key says nothing.

    Nothing to convert — a format 1 entry is already a valid format 2 one, and an absent
    ``sources`` list reads as *nobody recorded where this test came from* rather than as a
    test with no origin. The version is bumped all the same, because ``write`` rebuilds
    every row from the record: a build that did not know the key would drop it, which is
    FORMAT.md's rule for when a bump is owed.
    """
    return dict(data)


DATA_FORMAT = ModuleDataFormat(MODULE_ID, version=2, migrations=(_to_format_2,))

# What a test was read out of. Two kinds, one flat shape: a ``spec`` source names a
# document in the project's spec index and, usually, the passage it quotes; a ``note``
# source names an implementation note by its id. One record rather than two classes
# because every reader — the column, the list under the table, the export, the lint —
# wants the same four questions answered, and a kind is one of them.
SPEC_SOURCE = "spec"
NOTE_SOURCE = "note"
SOURCE_KINDS = (SPEC_SOURCE, NOTE_SOURCE)

# What a test on a step no feature gathers is filed under — work that reaches no release.
# Said once here because the tab's headings and an exported pack's headings are the same
# claim, and `dplanner project lint` reports those steps as `scope.ungathered`.
UNGATHERED = "Not in any feature"

# Ids people say out loud and write in a bug report: T100, T101, … Three digits from
# the start so every id in a project is the same width, and high enough that nobody
# mistakes one for a count of anything.
TEST_ID_PREFIX = "T"
FIRST_TEST_NUMBER = 100


@dataclass(frozen=True)
class TestSource:
    """Where a test came from: a passage of a specification, or an implementation note.

    ``ref`` is the document's name for a ``spec`` source and the note's id (``N3``) for a
    ``note`` one — in both cases the name every other verb addresses that thing by, so a
    renamed document or a superseded note is followed by whoever owns it rather than by a
    copy kept here. ``quote`` is the passage itself, which is also what makes the source
    readable in a tooltip without opening anything, and ``digest`` is the document's
    digest when it was cited, so a later reader can tell the spec moved on.
    """

    # pytest collects any class called Test*; the opt-out is cheaper than a worse name,
    # exactly as on ``Test`` below.
    __test__ = False

    kind: str  # One of SOURCE_KINDS.
    ref: str
    quote: str = ""
    page: int | None = None
    digest: str = ""

    @property
    def words(self) -> str:
        """One line naming this source, for a column, a row and an exported heading."""
        where = f" p. {self.page}" if self.page is not None else ""
        return f"{self.ref}{where}"


@dataclass(frozen=True)
class SourceFacts:
    """What a source is *called* where it lives, and what it says.

    The record holds a pointer and nothing else, so every reader that wants to print a
    source has to ask whoever owns it — the spec index for a document, the note log for a
    note. That answer is this, and the composition root is what composes it: this module
    imports neither of those, and a title copied into the record would be wrong the day
    somebody renamed the thing.
    """

    label: str
    detail: str = ""  # The quoted passage, or what the note says.
    found: bool = True  # False when nothing of that name is there any more.


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
    sources: tuple[TestSource, ...] = ()


def read_sources(value: Any) -> tuple[TestSource, ...]:
    """The sources a row carries — an unreadable one reads as absent, never as an error.

    A kind this build does not know is dropped rather than kept: every reader would have
    to guess what to do with it, and a source nobody can open is worse than a test that
    admits it has none.
    """
    if not isinstance(value, list):
        return ()
    found = []
    for raw in value:
        if not isinstance(raw, dict) or raw.get("kind") not in SOURCE_KINDS:
            continue
        if not isinstance(raw.get("ref"), str) or not raw["ref"]:
            continue
        page = raw.get("page")
        found.append(
            TestSource(
                kind=raw["kind"],
                ref=raw["ref"],
                quote=str(raw.get("quote", "") or ""),
                page=page if isinstance(page, int) and not isinstance(page, bool) else None,
                digest=str(raw.get("digest", "") or ""),
            )
        )
    return tuple(found)


def source_rows(sources: Sequence[TestSource]) -> list[dict[str, Any]]:
    """The sources as rows on disk — what is empty is left out, as FORMAT.md asks."""
    return [
        {
            "kind": source.kind,
            "ref": source.ref,
            **({"quote": source.quote} if source.quote else {}),
            **({"page": source.page} if source.page is not None else {}),
            **({"digest": source.digest} if source.digest else {}),
        }
        for source in sources
    ]


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
            sources=read_sources(entry.get("sources")),
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
                    **({"sources": source_rows(test.sources)} if test.sources else {}),
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
