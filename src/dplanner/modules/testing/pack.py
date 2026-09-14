"""What a pack of tests *is*, and how each format renders one.

A test is written to be *executed*, and the person or the tool executing it often has no
DPlanner: a contract tester, a QA supplier, an agent driving a browser in another
repository. So the roster has to be able to leave — as plain files, with the screenshots
beside them, in a shape a reader can open without being told how.

**One format today and a list of them tomorrow.** :class:`ExportFormat` is a name and a
render; ``FORMATS`` is the list the dialog offers and the only thing a second format has
to join. That is why this is a *writer* rather than a markdown function: HTML, one file
per test, a Playwright skeleton — each is a row there and nothing else changes.

**A format returns files, it does not write them.** ``render`` answers a list of
:class:`ExportFile` — a path inside the pack and its bytes — so the same pack becomes a
folder or a zip with no format knowing which, and a test can assert on what a pack holds
without a temporary directory. It also keeps this half Qt-free: the pictures a test marks
are rung by the *caller* and arrive here as bytes. ``export.py`` beside this is the
window's half — it reads the plan into a :class:`TestPack`, asks, writes and says what
came of it.

**The folder is flat and says what it is.**

    Widget tests 2026-09-14 1432/
      tests.md            every test, under the feature it belongs to
      assets/T100-1.png   the pictures, named for the test and where in it they sit

One markdown file rather than one per test: a tester reads a pack start to finish, prints
it, or searches it, and forty files help with none of those. The pictures are copied under
names built from the test and its position in the body, never their content-addressed
ones, because ``a41f0e9c2b.png`` tells the person who receives the pack nothing.

Qt-free by rule — see ``HEADLESS_FILES`` in ``tests/test_architecture.py``.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath

from dplanner.domain.assets import ClickTarget, without_fragment
from dplanner.modules.testing.aspect import (
    NOTE_SOURCE,
    SourceFacts,
    Test,
    TestSource,
)

MARKDOWN = "markdown"
ASSETS_DIR = "assets"
BODY_NAME = "tests.md"
NO_SOURCE = "_No source recorded._"
NO_BODY = "_This test has no steps written yet._"


@dataclass(frozen=True)
class Picture:
    """One image a test's body links, ready to travel: where it is linked from, and what
    the pack should call it.

    ``data`` is what the pack carries — already rung, when the body marked a click target
    on it, because whoever receives the pack has no reader that would draw the ring.
    """

    reference: str  # Exactly as the body writes it, fragment and all.
    name: str  # The name inside the pack's assets directory.
    data: bytes
    targets: tuple[ClickTarget, ...] = ()


@dataclass(frozen=True)
class ExportedTest:
    """One test as the pack says it: the record, where it sits, and what travels with it."""

    test: Test
    step_title: str
    group: str  # The feature it belongs to, or UNGATHERED.
    sources: tuple[tuple[TestSource, SourceFacts], ...] = ()
    pictures: tuple[Picture, ...] = ()
    result: str = ""  # How it last did, in the words the window uses; "" for never run.


@dataclass(frozen=True)
class TestPack:
    """Everything one export writes, assembled before a format sees it."""

    __test__ = False  # pytest collects any class called Test*; see ``aspect.Test``.

    project: str
    tests: tuple[ExportedTest, ...]
    day: str = ""  # When the pack was made, for the line under the heading.
    note: str = ""  # Which tests these are — the whole roster, or one feature's.


@dataclass(frozen=True)
class ExportFile:
    """One file inside the pack: a relative path, and its bytes."""

    path: str
    data: bytes


@dataclass(frozen=True)
class ExportFormat:
    """One way of writing a pack out. The dialog lists these and nothing else."""

    id: str
    label: str  # What the dropdown says.
    render: Callable[[TestPack], list[ExportFile]] = field(repr=False)


def render_markdown(pack: TestPack) -> list[ExportFile]:
    """The pack as one markdown document and the pictures it links."""
    lines = [f"# {pack.project} — tests", ""]
    if pack.note:
        lines += [pack.note, ""]
    if pack.day:
        lines += [f"Exported {pack.day}.", ""]
    lines += [
        "These are acceptance tests: each one is executed against the running product by "
        "a person or by an automated tool. None of them is a unit test.",
        "",
    ]
    files: list[ExportFile] = []
    group = None
    for entry in pack.tests:
        if entry.group != group:
            group = entry.group
            lines += [f"## {group}", ""]
        lines += _test_lines(entry)
        files += [
            ExportFile(f"{ASSETS_DIR}/{picture.name}", picture.data) for picture in entry.pictures
        ]
    body = "\n".join(lines).rstrip() + "\n"
    return [ExportFile(BODY_NAME, body.encode("utf-8")), *files]


def _test_lines(entry: ExportedTest) -> list[str]:
    test = entry.test
    lines = [f"### {test.id} — {test.title or 'Untitled test'}", ""]
    lines += [f"**On step:** {entry.step_title}", ""]
    lines += ["**From:**", ""]
    if entry.sources:
        lines += [f"- {_source_line(source, facts)}" for source, facts in entry.sources]
    else:
        lines += [NO_SOURCE]
    lines += ["", "**Steps:**", ""]
    lines += [_rewritten(test.body, entry.pictures) if test.body.strip() else NO_BODY]
    if entry.result:
        lines += ["", f"_Last result: {entry.result}._"]
    lines += ["", "---", ""]
    return lines


def _source_line(source: TestSource, facts: SourceFacts) -> str:
    kind = "Implementation note" if source.kind == NOTE_SOURCE else "Specification"
    page = f", p. {source.page}" if source.page is not None else ""
    quote = f" — “{' '.join(facts.detail.split())}”" if facts.detail else ""
    return f"{kind}: **{facts.label}**{page}{quote}"


def _rewritten(body: str, pictures: Sequence[Picture]) -> str:
    """The body with every asset link pointed at the pack's own copy.

    Matched through the link syntax rather than by replacing the name as a substring,
    because a link that marks a click target carries a ``#…`` fragment after the name and
    a plain replace would leave that fragment stranded on the new one — pointing at part
    of a picture the pack has already had the ring painted into.
    """
    by_name = {picture.reference: f"{ASSETS_DIR}/{picture.name}" for picture in pictures}

    def point(match: re.Match[str]) -> str:
        found = by_name.get(without_fragment(match.group(1)))
        return match.group(0) if found is None else f"]({found})"

    return _LINK.sub(point, body.strip())


# The target of a markdown link or embed — what ``_rewritten`` re-points.
_LINK = re.compile(r"\]\(\s*([^)\s]+)\s*\)")


FORMATS: tuple[ExportFormat, ...] = (
    ExportFormat(id=MARKDOWN, label="Markdown and screenshots", render=render_markdown),
)


def format_of(format_id: str) -> ExportFormat:
    """The format by id; the first one for an id this build does not have."""
    return next((one for one in FORMATS if one.id == format_id), FORMATS[0])


def picture_name(test_id: str, position: int, reference: str, suffix: str = "") -> str:
    """What a picture is called inside the pack: the test, and where in its body it sits.

    Never the content-addressed name the plan stores it under: the person who opens the
    pack has to be able to tell which picture goes with which test, and ``a41f0e9c2b.png``
    cannot. The suffix is the original's, unless ``suffix`` overrides it — a picture whose
    click targets were rung on the way out is re-encoded, and its name has to follow.
    """
    kept = suffix or PurePosixPath(without_fragment(reference)).suffix.lower() or ".png"
    return f"{test_id}-{position}{kept}"


def default_name(project: str, when: datetime | None = None) -> str:
    """``Widget tests 2026-09-14 1432`` — what the save dialog opens on.

    Timestamped because an export is a *moment*: the second pack made on a Tuesday must
    not silently replace the first, and a reader with three of them in a folder needs to
    know which is which without opening them.
    """
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H%M")
    return f"{slug(project) or 'project'} tests {stamp}"


def slug(text: str) -> str:
    """``text`` as a filename people can type: the characters every platform keeps."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.-]", "", text)).strip()
