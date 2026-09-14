"""The window's half of exporting tests: gathering the pack, asking, writing, saying.

``pack.py`` says what a pack *is* and how a format renders one; this reads the plan to
build it and puts it on disk. The split is the report's — modules say, one renderer shows
— and it is what keeps the format list Qt-free while the pictures that travel with a pack
are painted with a ``QPainter``.

**The dialog asks three things and nothing else**: which format, where to put it, and
whether to zip it. What is being exported is *said* rather than asked — the tests picked
in the table, or the whole roster when nothing is picked — because the person clicked the
verb from a surface that already shows the answer, and a dialog that re-asks it makes them
doubt what they were looking at.

**The name is offered with a timestamp.** An export is a moment; two on one afternoon must
not be the same file. ``export.default_name`` composes it and the save dialog opens on it.

**Zipping is offered, never assumed.** A folder is what a person opens; a zip is what they
send. The switch remembers nothing — it is a fact about this one export, not a preference.

**Written on the GUI thread, deliberately.** ``TaskRunner`` is for work that blocks — the
network, a git checkout, a report over a whole plan. A pack is a markdown file and the
screenshots a few tests link, read from the same local area every thumbnail in the window
is already read from synchronously; a worker here would buy nothing and cost a thread
alive at teardown, which is the suite's SIGSEGV shape.
"""

import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QWidget

from dplanner.domain.assets import targets_by_asset
from dplanner.domain.model import Library, Project, StepId
from dplanner.domain.scope import ScopeKind, gatherers
from dplanner.domain.store import FilesFor
from dplanner.framework.click_targets import marked_bytes
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.widgets import block, caption, note
from dplanner.modules.testing import runs
from dplanner.modules.testing.aspect import (
    MODULE_ID,
    UNGATHERED,
    SourceFacts,
    Test,
    TestSource,
    project_tests,
)
from dplanner.modules.testing.pack import (
    FORMATS,
    ExportedTest,
    ExportFile,
    ExportFormat,
    Picture,
    TestPack,
    picture_name,
)
from dplanner.modules.testing.view import word

DIALOG_TITLE = "Export Tests"
FORMAT_CAPTION = "Format"
FORMAT_HINT = "What the pack is written as. The screenshots travel whatever this says."
ZIP_LABEL = "Zip the folder"
ZIP_HINT = "One file to send, rather than a folder to open."
PRIMARY = "Choose Folder…"
PRIMARY_ZIP = "Choose File…"


@dataclass(frozen=True)
class Chosen:
    """What the dialog came to: where to write, in what format, zipped or not."""

    path: Path
    format: ExportFormat
    zipped: bool


class ExportDialog(DialogFrame):
    """Which format, zipped or not, and where — then the save dialog does the asking."""

    def __init__(self, what: str, suggested: str, parent: QWidget | None = None) -> None:
        super().__init__(DIALOG_TITLE, parent)
        self._suggested = suggested
        self._chosen: Chosen | None = None

        self.body_layout.addWidget(note(what, self.body))
        self.format_box = QComboBox(self.body)
        for one in FORMATS:
            self.format_box.addItem(one.label, one.id)
        block(self.body_layout, caption(FORMAT_CAPTION, self.body), self.format_box)
        self.body_layout.addWidget(note(FORMAT_HINT, self.body))
        self.zip_box = QCheckBox(ZIP_LABEL, self.body)
        self.zip_box.setToolTip(ZIP_HINT)
        self.zip_box.toggled.connect(self._name_primary)
        self.body_layout.addWidget(self.zip_box)
        self.body_layout.addStretch(0)

        self.choose = self.set_primary(PRIMARY, self._pick)
        self.add_dismiss("Cancel")

    def _name_primary(self) -> None:
        """The primary says which dialog it is about to open, so the click is no surprise."""
        self.choose.setText(PRIMARY_ZIP if self.zip_box.isChecked() else PRIMARY)

    def chosen(self) -> Chosen | None:
        return self._chosen

    def _pick(self) -> None:
        zipped = self.zip_box.isChecked()
        start = Path.home() / (f"{self._suggested}.zip" if zipped else self._suggested)
        if zipped:
            picked, _filter = QFileDialog.getSaveFileName(
                self, DIALOG_TITLE, str(start), "Zip archives (*.zip)"
            )
        else:
            picked = QFileDialog.getExistingDirectory(self, "Export Tests Into")
        if not picked:
            return  # The reader backed out of the second dialog; this one stays open.
        path = Path(picked)
        if zipped and path.suffix.lower() != ".zip":
            path = path.with_suffix(".zip")
        if not zipped:
            # A folder picker answers where to put it, never what to call it: the pack
            # makes its own named folder there, so two exports never merge into one.
            path = path / self._suggested
        chosen = next(one for one in FORMATS if one.id == str(self.format_box.currentData() or ""))
        self._chosen = Chosen(path=path, format=chosen, zipped=zipped)
        self.accept()


def write_pack(files: Sequence[ExportFile], destination: Path, *, zipped: bool) -> Path:
    """Write the pack, as a folder or as one zip; answers where it landed.

    The two shapes are one function because a format never learns which it is: it answers
    files, and this decides whether each becomes a path on disk or an entry in an archive.
    """
    if zipped:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for one in files:
                archive.writestr(one.path, one.data)
        return destination
    for one in files:
        target = destination / one.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(one.data)
    return destination


def today_words() -> str:
    """The day the pack says it was made — a reader's own locale would not travel."""
    return date.today().isoformat()


def gather(
    library: Library,
    project: Project,
    *,
    wanted: Sequence[str],
    scope: StepId,
    scopes: Sequence[ScopeKind],
    feature_kind: str,
    facts_for: Callable[[TestSource], SourceFacts],
    files: FilesFor | None,
) -> TestPack:
    """Read the plan into a pack: the tests, what they cite, and the pictures they link.

    ``wanted`` is the picked tests, or empty for every live one — the same "nothing picked
    means the lot" the verb's own words promise. ``scope`` is only there to say so in the
    note under the heading; what is exported is ``wanted``, already narrowed by whoever
    called.
    """
    picked = set(wanted)
    pairs = [
        (step, test) for step, test in project_tests(project) if not picked or test.id in picked
    ]
    groups = _groups(library, project, scopes, feature_kind)
    outcomes = runs.latest_results(runs.read(project))
    entries = [
        ExportedTest(
            test=test,
            step_title=step.title or "Untitled step",
            group=groups.get(step.id, UNGATHERED),
            sources=tuple((source, facts_for(source)) for source in test.sources),
            pictures=_pictures(test, step.id, files),
            result=word(outcomes[test.id].result.status) if test.id in outcomes else "",
        )
        for step, test in pairs
    ]
    # Grouped, keeping the project's own order inside each — a stable sort over where the
    # group's first step sits. The same rule the table's headings follow, so a pack reads
    # in the order the tab showed it, and what nothing gathers lands last.
    ranks = {name: rank for rank, name in enumerate(dict.fromkeys(groups.values()))}
    last = len(ranks)
    ordered = sorted(entries, key=lambda one: ranks.get(one.group, last))
    return TestPack(
        project=project.title or "Untitled project",
        tests=tuple(ordered),
        day=today_words(),
        note=_note(project, scope, len(ordered), bool(picked)),
    )


def _note(project: Project, scope: StepId, count: int, picked: bool) -> str:
    """The line under the heading: which tests these are, in the reader's own terms.

    Worth a line because a pack is read away from the window that made it: "12 of the 40
    tests in this plan" is the difference between a partial pack and a missing one.
    """
    total = len(project_tests(project))
    tests = f"{count} test{'' if count == 1 else 's'}"
    scoped = project.step(scope) if scope else None
    if scoped is not None and not picked:
        where = scoped.title or "one step"
        return f"{tests} — everything behind **{where}**, of {total} in the plan."
    if picked and count != total:
        return f"{tests}, picked from the {total} in the plan."
    return f"Every test in the plan — {tests}."


def _groups(
    library: Library, project: Project, scopes: Sequence[ScopeKind], feature_kind: str
) -> dict[StepId, str]:
    """Which feature each step flows into — the heading its tests land under."""
    kind = next((one for one in scopes if one.id == feature_kind), None)
    if kind is None:
        return {}
    owners = gatherers(library, project, carried_by=kind.carried_by, stops_at=kind.stops_at)
    found: dict[StepId, str] = {}
    for step in project.steps:
        named = [
            owner.title or "Untitled step"
            for held in owners.get(step.id, ())
            if (owner := project.step(held)) is not None
        ]
        found[step.id] = " and ".join(named) if named else UNGATHERED
    return found


def _pictures(test: Test, step_id: StepId, files: FilesFor | None) -> tuple[Picture, ...]:
    """The pictures a test's body links, read out of the step's area and rung.

    A reference the area cannot answer is left out of the pack and left alone in the body:
    a broken link in an export is honest where a silently dropped picture is not.
    """
    if files is None:
        return ()
    marks = targets_by_asset(test.body)
    if not marks:
        return ()
    try:
        area = files(step_id, MODULE_ID)
    except KeyError:
        return ()  # The step has no directory yet — nothing has been flushed.
    found = []
    for position, (name, targets) in enumerate(marks.items(), start=1):
        data = area.read_bytes(name)
        if data is None:
            continue
        carried, suffix = marked_bytes(data, targets)
        found.append(
            Picture(
                reference=name,
                name=picture_name(test.id, position, name, suffix),
                data=carried,
                targets=targets,
            )
        )
    return tuple(found)
