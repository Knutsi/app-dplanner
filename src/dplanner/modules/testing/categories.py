"""Test categories: the open vocabulary a project files its tests under.

A roster of two hundred tests is a wall unless it is filed, and no closed list could name
the groups every project will want — so unlike the audience (``aspect.py``'s ``AUDIENCES``,
three words nothing outside testing has an opinion about) a category is **free text**, and
the catalogue lives beside the *project* rather than in the application.

Three rules earn their own paragraph:

**A test names its category by its words.** There is no minted id, so ``dplanner test set
T100 --category 'Import'`` is the whole story, a diff says which group a test moved to, and
an agent that has never seen this project can file a test from the catalogue it just read.
The cost is that renaming is a **refactor** rather than an edit — :func:`renamed` rewrites
every test that carries the old words — and that is the honest price: the alternative is an
id nobody can type and a label that drifts from it.

**The catalogue is stored; membership is derived.** A :class:`Category` is a name and a
glyph, and the list exists so the categories can be written *before* the tests that will
fill them — the agent reading a spec and laying out the groups the tests will arrive into.
What is *in* a category is never stored: :func:`counts` walks the tests, the same rule the
topological order keeps (``CLAUDE.md``). A category a test names but the catalogue does not
is still a real category — :func:`catalog` appends it — so a typo is visible and fixable
rather than a test that has quietly fallen out of every list.

**A test that names none reads as** :data:`UNCATEGORISED`. The same tolerance the audience
shows, and for the same reason: a plan written before categories existed is not wrong, it
is unfiled, and ``project lint``'s ``test.category`` is what carries it over a test at a
time rather than a migration guessing an answer.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

import dataclasses
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from dplanner.cli.command import CliError
from dplanner.domain.model import Project, StepId
from dplanner.modules.testing.aspect import MODULE_ID, Test, project_entry, project_tests, read

# What a refactor does to one step's tests: the whole list in, the whole list out. A rename
# and a removal are the same shape asked twice, which is what lets `rewrite` below find the
# steps a change actually touches without knowing which change it was handed.
type TestsChange = Callable[[Sequence[Test]], list[Test]]

# What a test with nothing stored is filed under. A heading rather than a category: it is
# never in the catalogue, it cannot be renamed, and it always sorts last.
UNCATEGORISED: Final = "Uncategorised"

# The glyphs a category may wear, from the vendored Tabler set (``theme/glyphs/``). A
# curated subset rather than the whole directory, because a picker of seventy-four glyphs —
# undo, redo, bold — is a wall of its own; these are the ones that say something about a
# *kind of test*. Named here, in the Qt-free half, so the CLI can refuse an unknown one
# without a graphics stack; ``tests/modules/test_testing_categories.py`` checks every name
# still has an SVG beside ``theme/icons.py``.
ICONS: Final[tuple[str, ...]] = (
    "beaker",
    "shield",
    "spark",
    "layers",
    "tag",
    "eye",
    "clock",
    "gauge",
    "code",
    "image",
    "table",
    "list",
    "star",
    "check",
    "play",
    "leaf",
    "folder",
    "camera",
    "clipboard",
    "container",
    "coverage",
    "graph",
    "region",
    "ticket",
    "find",
    "read",
    "info",
    "problem",
    "project",
    "step",
    "sweep",
)


@dataclass(frozen=True)
class Category:
    """One group a project files its tests under: its words, and the glyph it wears."""

    name: str
    icon: str = ""  # A key from ICONS; "" is a category with no glyph, which is fine.


def read_catalog(project: Project) -> list[Category]:
    """The categories stored beside ``project``, in the order they were written.

    Order is the catalogue's own — the sequence an agent laid the groups out in reads
    better than alphabetical, which files *Smoke* after *Regression* for no reason.
    Unreadable entries read as absent, never as an error.
    """
    raw = project.module_data.get(MODULE_ID, {}).get("categories")
    if not isinstance(raw, list):
        return []
    found: list[Category] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        icon = str(entry.get("icon", "")).strip()
        found.append(Category(name, icon if icon in ICONS else ""))
    return found


def write_catalog(project: Project, categories: Sequence[Category]) -> dict[str, Any]:
    """The project entry to store. An empty catalogue removes the key, not the runs."""
    return project_entry(
        project,
        categories=[
            {"name": category.name, **({"icon": category.icon} if category.icon else {})}
            for category in categories
        ],
    )


def category_of(test: Test) -> str:
    """What the test counts as: what it named, or :data:`UNCATEGORISED`.

    The one derivation every view, grouping and export reads, so an unfiled test lands
    somewhere honest instead of falling out of the list. One reader asks the raw
    ``test.category`` instead — ``lint`` — because its question is the other one: *has
    anybody actually said?*
    """
    return test.category or UNCATEGORISED


def catalog(project: Project) -> list[Category]:
    """Every category this project has: the stored ones, then any a test names by itself.

    The second half is what keeps a typo visible. A category only a test knows about wears
    no glyph and sorts after the catalogue, alphabetically — it is not a decision anybody
    recorded, so it does not get to claim a position among the ones that were.
    """
    stored = read_catalog(project)
    known = {category.name.casefold() for category in stored}
    # Archived tests count towards what categories *exist*: taking a test off the roster is
    # not filing it somewhere else, and the last live test of a group being archived must
    # not take the group's name with it.
    loose = sorted(
        {
            test.category
            for _step, test in project_tests(project, archived=True)
            if test.category and test.category.casefold() not in known
        },
        key=str.casefold,
    )
    return [*stored, *(Category(name) for name in loose)]


def counts(project: Project, *, archived: bool = False) -> dict[str, int]:
    """How many tests each category holds, keyed by name, :data:`UNCATEGORISED` included.

    Derived on every read (``CLAUDE.md``'s *Derived facts are computed, never stored*), and
    every catalogued category is present even at nought — a group nobody has filled is what
    the editor's row and the agent's next batch are both about.
    """
    found = {category.name: 0 for category in catalog(project)}
    found.setdefault(UNCATEGORISED, 0)
    for _step, test in project_tests(project, archived=True):
        if test.archived and not archived:
            continue
        found[category_of(test)] = found.get(category_of(test), 0) + 1
    return found


def find(categories: Sequence[Category], name: str) -> Category | None:
    """The category of these words, matched without regard to case — the way a person
    typing one and an agent writing one both expect it to be matched."""
    folded = name.strip().casefold()
    return next((c for c in categories if c.name.casefold() == folded), None)


def check_icon(icon: str) -> str:
    """``icon`` if it is one of :data:`ICONS`; a CliError naming them all otherwise.

    ``check_audience``'s shape one vocabulary over: a wrong guess teaches the whole set,
    which is what saves an agent a verb whose only job is to list a lookup table.
    """
    if icon and icon not in ICONS:
        raise CliError(f"no such icon {icon!r} — one of: {', '.join(ICONS)}")
    return icon


def check_name(name: str) -> str:
    """A category's words, trimmed — refused when they are blank or reserved.

    :data:`UNCATEGORISED` is what *no* category reads as, so a category actually called it
    would make the heading mean two things at once.
    """
    trimmed = name.strip()
    if not trimmed:
        raise CliError("a category needs a name")
    if trimmed.casefold() == UNCATEGORISED.casefold():
        raise CliError(f"{UNCATEGORISED!r} is what a test with no category reads as")
    return trimmed


def refiled(tests: Sequence[Test], test_ids: Iterable[str], category: str) -> list[Test]:
    """``tests`` with the named ones filed under ``category`` — "" files them under none."""
    wanted = set(test_ids)
    return [
        dataclasses.replace(test, category=category) if test.id in wanted else test
        for test in tests
    ]


def renamed(tests: Sequence[Test], old: str, new: str) -> list[Test]:
    """``tests`` with every one filed under ``old`` filed under ``new`` — the refactor.

    Matched without regard to case, so renaming *import* to *Import* also tidies up the
    tests an agent filed under the other spelling.
    """
    folded = old.casefold()
    return [
        dataclasses.replace(test, category=new) if test.category.casefold() == folded else test
        for test in tests
    ]


def rewrite(project: Project, change: TestsChange) -> dict[StepId, list[Test]]:
    """Every step whose tests ``change`` actually alters, and what they become.

    Returned per step so the caller pushes one command per step — and none at all for a
    step the change does not touch, which is what keeps a rename that hits four tests from
    rewriting forty files.
    """
    found: dict[StepId, list[Test]] = {}
    for step in project.steps:
        before = read(step)
        if not before:
            continue
        after = change(before)
        if after != before:
            found[step.id] = after
    return found
