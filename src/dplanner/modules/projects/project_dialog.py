"""The Project dialog: what a project is, where its plan and its code live, and what
both repositories have been up to.

*Project ▸ Settings…* — the name and summary above a rule, then **one column per
repository**, parted by a vertical rule: the code on the left, the plan on the right,
each with its branch over a well of rows, and under the well the two facts that column
answers — *which repository is it* and *where is it on this machine* — with a ⋯ menu of
everything that changes either. The divide is the teaching: the same two lines under both
columns are what says these are two repositories and not three fields.

Every edit is live and undoable (the name and summary, the code repository and the
colocation go through the undo stack; the checkout is written straight into the library
file, a per-machine fact), so the dialog carries Close and nothing else — DESIGN.md's
rule, the step details dialog the precedent — and one instance serves the window,
re-aimed by ``show_project``. What the last request came to is said in the footer's
status slot.

The logs are read off the GUI thread: one task body reads both histories and the code
repository's open pull requests and hands back one :class:`_Logs`, stamped with the
project it was asked for, so an answer for a project the dialog has since left is dropped.
A pull request row names the step that carries it, when one does — the github aspect's
record, looked up by the composition root — and activating the row opens the PR. Where
the plan has no repository of its own the plan column offers *Set up a plan repository…*
instead of a log: its history *is* the code's, and showing the same commits twice would
say they were apart. Cloning, publishing and creating on GitHub run in a second task body,
and their outcome lands in the model on the GUI thread through one ``_done`` signal.

*File ▸ New Project…* is the same dialog in **create mode**: a form, because there is no
history yet to read — the name, the summary, then the plan repository, the folder inside
it, the code repository and its checkout as captioned blocks, and Create as the primary,
refused in words until the plan has a home. **Both repositories are picked rather than
typed**, and each field carries the ⋯ of the other ways in: the plan's is the
:class:`~dplanner.modules.projects.repo_picker.RepoPicker`, the code's is a list of what
this library already plans over *Pick from GitHub…* and *Clone into Repositories Folder* —
and naming code another project here plans brings that project's checkout with it, because
a second plan for one repository needs no second clone. It answers a
:class:`NewProjectSpec`; the module seeds the project and connects it, so the dialog writes
nothing into the library.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.fsio import slugify
from dplanner.core.storage.locations import (
    canonical_remote,
    origin_url,
    remote_label,
)
from dplanner.core.storage.provider import StorageError
from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.locations import (
    CODE,
    Location,
    Placement,
    located_folder,
    next_id,
    place,
    primary_code,
    replaced,
    without,
)
from dplanner.domain.model import Library, NodeId, Project
from dplanner.domain.plan_repo import ago
from dplanner.domain.repositories import ACCEPTED, LEGACY, SEPARATED, RepositoryFacts
from dplanner.framework.cards import card_rule
from dplanner.framework.dialog import DialogFrame, LinePrompt
from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    EMPHASIS_ROLE,
    RULE_ROLE,
    TwoLineDelegate,
)
from dplanner.framework.signalling import Tone
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.widgets import EmptyState, block, caption, confirm, note, quiet
from dplanner.modules.projects.location_dialog import LocationDialog
from dplanner.modules.projects.locations_table import LocationsTable
from dplanner.modules.projects.repo_picker import (
    Entry,
    GhRepoListDialog,
    PlanTarget,
    RepoAction,
    RepoPicker,
    github_name_problem,
    menu_button,
    popup_menu,
)
from dplanner.modules.projects.repos import (
    LOG_LIMIT,
    MOVE_PLAN,
    SET_UP_PLAN,
    PullRequest,
    RepoLines,
    RepoLog,
    RepositoryServices,
    code_lines,
    github_url,
    plan_lines,
    shown_path,
)
from dplanner.modules.projects.repositories_folder import (
    ensure_repositories_folder,
    repositories_folder,
)
from dplanner.theme.icons import (
    ICON_SIZE,
    branch_icon,
    clone_icon,
    code_icon,
    edit_icon,
    external_icon,
    find_icon,
    folder_icon,
    move_icon,
    plus_icon,
    project_icon,
    pull_request_icon,
    trash_icon,
)
from dplanner.theme.themes import Theme
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, ROW_LINE_GAP, SECTION_GAP

URL_ROLE = int(Qt.ItemDataRole.UserRole) + 10

SETTINGS = "settings"
CREATE = "create"
SETTINGS_SIZE = (940, 770)
CREATE_SIZE = (770, 620)
# What the plan column says where the plan has no history of its own to show.
SETUP_WORDS = "The plan's history is the code's — it has no repository of its own."


@dataclass(frozen=True)
class NewProjectSpec:
    """What Create asked for — seeded and connected by the module, never by the dialog."""

    title: str
    summary: str
    plan: PlanTarget
    folder: str
    locations: tuple[Location, ...]
    # (repository, path): where this machine has a named repository — a clone the person
    # ran from the form — to record per repository once the project exists.
    checkouts: tuple[tuple[str, Path], ...] = ()

    @property
    def target(self) -> Path:
        return self.plan.root / self.folder

    @property
    def repository(self) -> str:
        """The primary code repository the draft names, "" for none."""
        primary = primary_code(self.locations)
        return primary.repository if primary is not None else ""


def restyle(widget: QWidget, name: str) -> None:
    """Give a widget another stylesheet name and repaint it under the new rule."""
    if widget.objectName() == name:
        return
    widget.setObjectName(name)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def glyph_label(parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setFixedSize(ICON_SIZE, ICON_SIZE)
    return label


class ElidedLabel(QLabel):
    """A one-line label that shows what it has room for and elides the rest.

    Elision happens in the **paint**, never in a resize: a widget that rewrites its own
    text while being resized can change its size hint and drive the layout in a circle,
    which is the shape behind the `suite-crash` skill's layout-loop crash. Painting cannot.
    The full text is the tooltip, so nothing is lost — and a path elides from the left,
    because a path's tail is what names it.
    """

    def __init__(self, mode: Qt.TextElideMode, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        # Ignored horizontally: the label asks for no width of its own, so a long path
        # cannot stretch the dialog — it elides into whatever the column has.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        shown = self.fontMetrics().elidedText(self.text(), self._mode, self.width())
        painter.drawText(
            self.rect(), int(self.alignment()) | int(Qt.AlignmentFlag.AlignVCenter), shown
        )


def smaller(widget: QWidget, points: float = 1.0) -> None:
    """A step down from the surface's font, for a line that states a fact under the thing
    it is about. Guarded: a font sized in pixels reports a point size of -1."""
    font = widget.font()
    if font.pointSizeF() > 0:
        font.setPointSizeF(max(font.pointSizeF() - points, 1.0))
        widget.setFont(font)


@dataclass(frozen=True)
class _Logs:
    """One fetch's answer, stamped with the project it was asked for."""

    project_id: str
    code: RepoLog | None
    plan: RepoLog | None
    prs: tuple[PullRequest, ...]
    steps: Mapping[int, str]
    gh_refusal: str | None
    error: str


class RepositoryColumn(QWidget):
    """One repository, top to bottom: a caption with the branch it is on, a well of rows —
    open pull requests in bold above the rule, commits below it — and a footer saying which
    repository this is and where it is on this machine, with a ⋯ menu of the verbs that
    change either.

    The column knows nothing about *which* repository it renders: it is handed the two
    lines to show and a function returning the menu's entries, which is what lets the code
    and the plan be the same widget twice and read as a pair.
    """

    activated = QtSignal(str)  # A pull request row's URL.
    setup_requested = QtSignal()  # The empty state's verb, where the column carries one.

    def __init__(
        self,
        caption_text: str,
        entries: Callable[[], Sequence[Entry]],
        parent: QWidget | None = None,
        *,
        verb: str = "",
    ) -> None:
        super().__init__(parent)
        self._color = ""
        self._entries = entries
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(CAPTION_GAP)

        # A child layout joins its parent before it is filled: a parentless one leaves the
        # item wrappers it was given alive on the Python side (CLAUDE.md's layout rules).
        header = QHBoxLayout()
        layout.addLayout(header)
        self.glyph = glyph_label(self)
        self.caption = caption(caption_text, self)
        self.branch = QLabel(self)
        self.branch.setObjectName("LogBranch")
        header.setSpacing(CAPTION_GAP)
        header.addWidget(self.glyph)
        header.addWidget(self.caption)
        header.addStretch(1)
        header.addWidget(self.branch)

        self.well = QListWidget(self)
        self.well.setObjectName("LogWell")
        self.well.setItemDelegate(TwoLineDelegate(self.well))
        self.well.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.well.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.well.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.well.itemActivated.connect(self._activate)
        # What stands where the rows would be — a message, or the one verb that puts a
        # history here (DESIGN.md's *Empty states*): the plan column's *Set up a plan
        # repository…*, whose button is the same plain button every empty state offers.
        self.empty = EmptyState(
            "",
            self,
            stands_in_for=self.well,
            action=(verb, self.setup_requested.emit) if verb else None,
        )
        self.setup_button = self.empty.button
        if self.setup_button is not None:
            quiet(self.setup_button)  # The accent is restyled on while the shape drifts.
            self.setup_button.setObjectName("PlanSetupButton")
        layout.addWidget(self.well, 1)
        layout.addWidget(self.empty, 1)

        # The footer: what this repository is, where it is here, and everything you can do
        # to either — small, because it states facts under the thing they are about.
        footer = QGridLayout()
        layout.addLayout(footer)
        self.identity = ElidedLabel(Qt.TextElideMode.ElideRight, self)
        self.location = ElidedLabel(Qt.TextElideMode.ElideLeft, self)
        # Each line's own name, to return to after a spell greyed as #RepoLineMissing.
        self._names = {self.identity: "RepoIdentity", self.location: "RepoLocation"}
        for label, name in self._names.items():
            label.setObjectName(name)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            smaller(label)
        self.menu_button = menu_button(
            f"What you can do with the {caption_text.lower()} repository", self
        )
        self.menu_button.clicked.connect(self.popup)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setHorizontalSpacing(FIELD_GAP)
        footer.setVerticalSpacing(ROW_LINE_GAP)
        footer.addWidget(self.identity, 0, 0)
        footer.addWidget(self.location, 1, 0)
        footer.addWidget(self.menu_button, 0, 1, 2, 1, Qt.AlignmentFlag.AlignVCenter)
        footer.setColumnStretch(0, 1)
        # A line with nothing to say still holds its row, so the two footers stay level.
        for index, line in enumerate((self.identity, self.location)):
            footer.setRowMinimumHeight(index, line.fontMetrics().height())

    # -- what it shows ---------------------------------------------------------------------------

    def paint(self, painter: Callable[[str], QIcon], color: str) -> None:
        self._color = color
        self.glyph.setPixmap(painter(color).pixmap(ICON_SIZE, ICON_SIZE))

    def show_facts(self, lines: RepoLines) -> None:
        """The footer's two lines, greyed where they name what is missing."""
        for label, text, missing in (
            (self.identity, lines.identity, lines.identity_missing),
            (self.location, lines.location, lines.location_missing),
        ):
            label.setText(text)
            label.setToolTip(text)
            restyle(label, "RepoLineMissing" if missing else self._names[label])

    def show_log(
        self,
        log: RepoLog | None,
        prs: Sequence[PullRequest] = (),
        steps: Mapping[int, str] | None = None,
        *,
        empty_text: str = "No commits yet.",
    ) -> None:
        self.branch.setText(log.branch if log is not None else "")
        self.well.clear()
        named = steps or {}
        for index, pr in enumerate(prs):
            item = QListWidgetItem(f"#{pr.number} {pr.title}")
            item.setData(DETAIL_ROLE, f"{named.get(pr.number) or 'no step'} · {pr.head_ref}")
            item.setData(EMPHASIS_ROLE, True)
            item.setData(URL_ROLE, pr.url)
            item.setToolTip(pr.url)
            if self._color:
                item.setIcon(pull_request_icon(self._color))
            if index == len(prs) - 1:
                item.setData(RULE_ROLE, True)
            self.well.addItem(item)
        for entry in log.entries if log is not None else ():
            item = QListWidgetItem(entry.subject or "(no message)")
            item.setData(DETAIL_ROLE, f"{entry.author} · {ago(entry.when)}")
            self.well.addItem(item)
        if self.well.count():
            self.empty.say("")
        else:
            self.show_message(empty_text)

    def show_message(self, text: str) -> None:
        """Words where the rows would be, and no verb under them."""
        if self.setup_button is not None:
            self.setup_button.hide()
        self.empty.say(text)

    def show_setup(self, *, primary: bool) -> None:
        """The plan column's offer where the plan has no history of its own: the verb
        under the words, the accent on it while the shape is the one that drifts."""
        assert self.setup_button is not None  # Only the column built with a verb.
        restyle(self.setup_button, "PrimaryButton" if primary else "PlanSetupButton")
        self.branch.setText("")
        self.setup_button.show()
        self.empty.say(SETUP_WORDS)

    def rows(self) -> list[tuple[str, str]]:
        """What the well shows, line one and line two per row."""
        return [
            (item.text(), str(item.data(DETAIL_ROLE) or ""))
            for item in (self.well.item(index) for index in range(self.well.count()))
            if item is not None
        ]

    # -- the ⋯ menu ------------------------------------------------------------------------------

    def entries(self) -> list[Entry]:
        """What the menu would offer right now — asked afresh, and what a test reads."""
        return list(self._entries())

    def popup(self) -> None:
        popup_menu(self.menu_button, self.entries(), self._color)

    def _activate(self, item: QListWidgetItem) -> None:
        url = item.data(URL_ROLE)
        if url:
            self.activated.emit(str(url))


class ProjectDialog(DialogFrame):
    _fetched = QtSignal(object)  # _Logs, from the reading body.
    _done = QtSignal(str, object, str)  # (what, result, error), from a writing body.

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        services: RepositoryServices,
        tasks: TaskService,
        theme: ThemeService,
        *,
        move: Callable[[NodeId], None],
        mode: str = SETTINGS,
        parent: QWidget | None = None,
    ) -> None:
        create = mode == CREATE
        super().__init__(
            "New Project" if create else "Project",
            parent,
            size=CREATE_SIZE if create else SETTINGS_SIZE,
        )
        self.setObjectName("ProjectDialog")
        self.setMinimumSize(624, 504) if create else self.setMinimumSize(672, 552)
        self.mode = mode
        self._library = library
        self._undo = undo
        self._services = services
        self._tasks = tasks
        self._theme = theme
        self._move = move
        self._project_id: NodeId | None = None
        self._facts: RepositoryFacts | None = None
        self._gh_refusal: str | None = None
        self._refetch = False
        self._working = False
        self._reader = TaskRunner(tasks, parent=self)
        self._worker = TaskRunner(tasks, parent=self)
        # Everything that wears the theme's ink, as "repaint me in this colour". A mode
        # adds what it built, so _paint branches on nothing. The ink itself is kept for the
        # pop-ups, which are painted when they open rather than held.
        self._painters: list[Callable[[str], None]] = []
        self._ink = ""
        self._fetched.connect(self._on_logs)
        self._done.connect(self._on_done)

        # -- what the project is ---------------------------------------------------------
        body, layout = self.body, self.body_layout
        # The first field the frame finds is the first thing to type: the name.
        self.name_edit = QLineEdit(body)
        self.project_glyph = self._glyph(project_icon)
        self.name_edit.setObjectName("ProjectNameEdit")
        self.name_edit.setPlaceholderText("What this project is called")
        font = self.name_edit.font()
        font.setPointSize(font.pointSize() + 2)
        self.name_edit.setFont(font)
        self.name_edit.editingFinished.connect(self._commit_name)
        self.summary_edit = QLineEdit(body)
        self.summary_edit.setObjectName("ProjectSummaryEdit")
        self.summary_edit.setPlaceholderText("What it delivers, in one line (optional)")
        self.summary_edit.editingFinished.connect(self._commit_summary)

        grid = QGridLayout()
        layout.addLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(FIELD_GAP)
        grid.setVerticalSpacing(FIELD_GAP)
        grid.addWidget(self.project_glyph, 0, 0)
        grid.addWidget(self.name_edit, 0, 1)
        grid.addWidget(self.summary_edit, 1, 1)
        grid.setColumnStretch(1, 1)
        for row in (0, 1):
            grid.setRowMinimumHeight(row, ICON_SIZE)

        # -- the locations: every place the project is about, one row each ----------------
        # In settings mode the rows are the model's placements; in create mode a draft the
        # form holds until Create seeds the project. One widget, so neither mode can word
        # a row the other way.
        self._draft: list[Location] = []
        self._draft_checkouts: dict[str, Path] = {}
        self._cloning = ""  # The repository a clone in flight is of.
        self.locations = LocationsTable(services.roles, self._location_entries, body)
        self.locations.setObjectName("ProjectLocations")
        self.locations.add_requested.connect(self._add_location)
        self.locations.activated.connect(self._edit_location)
        self._painters.append(self.locations.paint)

        # -- one column per repository, parted by the divide that says they are two -------
        self.code_column = RepositoryColumn("Code", self._code_entries, body)
        self.code_column.setObjectName("CodeLogColumn")
        self.plan_column = RepositoryColumn("Plan", self._plan_entries, body, verb=SET_UP_PLAN)
        self.plan_column.setObjectName("PlanLogColumn")
        self._painters.append(lambda ink: self.code_column.paint(code_icon, ink))
        self._painters.append(lambda ink: self.plan_column.paint(branch_icon, ink))
        self.plan_column.setup_requested.connect(self._on_move)
        for log_column in (self.code_column, self.plan_column):
            log_column.activated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        logs = QWidget(body)
        logs.setObjectName("ProjectLogs")
        columns = QHBoxLayout(logs)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(SECTION_GAP)
        columns.addWidget(self.code_column, 1)
        columns.addWidget(card_rule(logs, vertical=True))
        columns.addWidget(self.plan_column, 1)

        # -- what is wrong; what the last request did goes in the footer's status slot ----
        self.warning = note("", body)
        self.keep_button = quiet(QPushButton("Keep it here", body))
        self.keep_button.setObjectName("KeepColocationButton")
        self.keep_button.setToolTip("The plan stays inside its code on purpose; stop warning")
        self.keep_button.clicked.connect(self._keep_here)
        self.warning_row = QWidget(body)
        self.warning_row.setObjectName("ColocationWarning")
        warning_layout = QHBoxLayout(self.warning_row)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        warning_layout.setSpacing(FIELD_GAP)
        warning_layout.addWidget(self.warning, 1)
        warning_layout.addWidget(self.keep_button)
        self.gh_note = note("", body)
        self.gh_note.hide()

        # -- create mode: a form, because there is nothing yet to have a menu about -------
        self.plan_picker: RepoPicker | None = None
        self.folder_edit: QLineEdit | None = None
        self._folder_touched = False

        self._unsubscribes = [
            library.field_changed.connect(self._on_field),
            library.structure_changed.connect(self._on_structure),
            services.checkout_changed.connect(self._on_checkout),
            theme.changed.connect(self._paint),
        ]
        self._paint(theme.current)
        if create:
            for unused in (logs, self.warning_row, self.gh_note):
                unused.hide()  # Nothing exists yet to read a log of or act on.
            self._build_create_form(services, tasks, theme)
        else:
            layout.addWidget(self.locations)
            layout.addWidget(card_rule(body))
            layout.addWidget(logs, 1)
            layout.addWidget(self.warning_row)
            layout.addWidget(self.gh_note)
            self.add_dismiss("Close")  # Every edit is live: Close, and nothing else.

    def _build_create_form(
        self, services: RepositoryServices, tasks: TaskService, theme: ThemeService
    ) -> None:
        """New Project…: the same name and summary, then the plan repository and the
        folder under their captions (DESIGN.md's *Forms*), then the Locations table over a
        draft — the code this project changes, and anything else it is about, added
        through the same Add ▾ and edited through the same ⋯ the settings mode has. No
        logs — there is no history yet to read. The answer is a :class:`NewProjectSpec`
        and Create is the primary."""
        body, layout = self.body, self.body_layout

        self.plan_picker = RepoPicker(services, tasks, allow_new=True, theme=theme, parent=body)
        self.plan_picker.setObjectName("PlanRepoPicker")
        self.plan_picker.changed.connect(self._revalidate_create)
        block(layout, caption("Plan repository", body), self.plan_picker)

        self.folder_edit = QLineEdit(body)
        self.folder_edit.setObjectName("ProjectFolderEdit")
        self.folder_edit.setPlaceholderText("folder name inside the plan repository")
        self.folder_edit.textEdited.connect(self._folder_typed)
        self.folder_edit.textChanged.connect(lambda _text: self._revalidate_create())
        self.name_edit.textChanged.connect(self._suggest_folder)
        self.target_label = note("", body)  # The path the two make, and only the path.
        block(layout, caption("Folder", body), self.folder_edit, self.target_label)

        layout.addWidget(self.locations, 1)
        self._show_locations()

        self.add_dismiss()
        self.create_button = self.set_primary("Create", self.accept)
        self._paint(theme.current)
        self._revalidate_create()

    # -- create mode ---------------------------------------------------------------------------

    def spec(self) -> NewProjectSpec | None:
        """What Create would make; None while a name, a plan repository or a folder is
        missing."""
        if self.plan_picker is None or self.folder_edit is None:
            return None
        title = self.name_edit.text().strip()
        plan = self.plan_picker.current()
        folder = self.folder_edit.text().strip()
        if not title or plan is None or not folder:
            return None
        return NewProjectSpec(
            title=title,
            summary=self.summary_edit.text().strip(),
            plan=plan,
            folder=folder,
            locations=tuple(self._draft),
            checkouts=tuple(self._draft_checkouts.items()),
        )

    def _known_repositories(self) -> list[str]:
        """The repositories this project and this library already name, each once, the
        project's primary code first — what the location dialog's combo lists. Read off
        the model: no disk, no gh, no subprocess."""
        found: list[str] = []
        primary = primary_code(self._rows())
        if primary is not None:
            found.append(primary.repository)
        for row in self._rows():
            if row.repository not in found:
                found.append(row.repository)
        for project in self._library.projects:
            for row in project.locations:
                if row.repository not in found:
                    found.append(row.repository)
        return found

    def _folder_typed(self, _text: str) -> None:
        self._folder_touched = True  # From here the name no longer dictates the folder.

    def _suggest_folder(self, title: str) -> None:
        if self.folder_edit is not None and not self._folder_touched:
            self.folder_edit.setText(slugify(title, fallback="project") if title.strip() else "")

    def _revalidate_create(self) -> None:
        """Create is refused with its reason, field by field, until the plan has a home."""
        if self.mode != CREATE:
            return
        assert self.plan_picker is not None and self.folder_edit is not None
        missing = (
            "Name the project first"
            if not self.name_edit.text().strip()
            else "Pick a plan repository"
            if self.plan_picker.current() is None
            else "Name the folder inside it"
            if not self.folder_edit.text().strip()
            else None
        )
        if missing is not None:
            self.target_label.setText("")
            self.refuse(missing)
            return
        spec = self.spec()
        assert spec is not None
        self.target_label.setText(shown_path(spec.target))
        self.refuse("A project already exists at that folder" if spec.target.exists() else None)

    def accept(self) -> None:
        if self.plan_picker is not None:
            self.plan_picker.remember()
        super().accept()

    # -- the locations, in both modes --------------------------------------------------------------

    def _rows(self) -> tuple[Location, ...]:
        """The table as this mode holds it: the draft, or the project's."""
        if self.mode == CREATE:
            return tuple(self._draft)
        project = self._project()
        return project.locations if project is not None else ()

    def _placements(self) -> tuple[Placement, ...]:
        if self.mode != CREATE:
            return self._facts.placements if self._facts is not None else ()
        checkouts = {
            row.canonical: found
            for row in self._draft
            if (found := self._draft_checkouts.get(row.repository))
            or (found := self._services.checkout_for(row.repository)) is not None
        }
        return tuple(
            place(row, checkouts=checkouts, plan_root=None, plan_remote="") for row in self._draft
        )

    def _show_locations(self) -> None:
        self.locations.show_rows(self._placements())

    def _set_locations(self, rows: tuple[Location, ...]) -> None:
        """The table, changed: into the draft, or — through the undo stack — into the
        fact the whole team shares, written into ``project.dproj``."""
        if self.mode == CREATE:
            self._draft = list(rows)
            self._show_locations()
            self._revalidate_create()
            return
        project = self._project()
        if project is None:
            return
        self._push_locations(project, rows)
        self._refresh()
        self._request_logs()

    def _push_locations(self, project: Project, locations: tuple[Location, ...]) -> None:
        if locations != project.locations:
            self._undo.push(SetFieldCommand(project.id, "locations", locations, view_origin=self))

    def _location_entries(self, location: Location) -> list[Entry]:
        """One row's ⋯: change it, place it on this machine, open it, drop it — the same
        list whatever the row's state, greyed with the reason where a verb cannot run."""
        role = self._services.roles.get(location.role)
        placement = next((p for p in self._placements() if p.location.id == location.id), None)
        gh = self._gh_reason()
        writes = role is None or role.writes
        return [
            RepoAction("Edit Location…", edit_icon, lambda: self._edit_location(location.id)),
            None,
            RepoAction(
                "Choose Checkout…",
                folder_icon,
                lambda: self._choose_location_checkout(location),
                "" if writes else "a read-only location is fetched on demand",
            ),
            RepoAction(
                "Clone into Repositories Folder",
                clone_icon,
                lambda: self._clone_location(location),
                gh
                or ("a read-only location is fetched on demand" if not writes else "")
                or ("already checked out here" if placement is not None and placement.here else ""),
            ),
            RepoAction(
                "Open on GitHub",
                external_icon,
                lambda: self._open_location(location),
                "" if "github.com" in location.repository else "not a GitHub repository",
            ),
            None,
            RepoAction("Remove Location", trash_icon, lambda: self._remove_location(location.id)),
        ]

    def _location_dialog(self, role_id: str, location: Location | None) -> LocationDialog | None:
        role = self._services.roles.get(role_id)
        if role is None:
            return None
        rows = self._rows()
        return LocationDialog(
            role,
            location_id=location.id if location is not None else next_id(rows),
            repositories=self._known_repositories(),
            location=location,
            checkout_for=self._checkout_for,
            record_checkout=lambda repository, root: self._record_checkout(root, repository),
            services=self._services,
            tasks=self._tasks,
            theme=self._theme,
            parent=self,
        )

    def _checkout_for(self, repository: str) -> Path | None:
        found = self._draft_checkouts.get(repository) if self.mode == CREATE else None
        return found if found is not None else self._services.checkout_for(repository)

    def _add_location(self, role_id: str) -> None:
        dialog = self._location_dialog(role_id, None)
        if dialog is None:
            return
        accepted = bool(dialog.exec())
        answer = dialog.answer() if accepted else None
        dialog.deleteLater()
        if answer is not None:
            self._set_locations(replaced(self._rows(), answer))
            self.locations.select(answer.id)

    def _edit_location(self, location_id: str) -> None:
        location = next((row for row in self._rows() if row.id == location_id), None)
        if location is None:
            return
        dialog = self._location_dialog(location.role, location)
        if dialog is None:
            return
        accepted = bool(dialog.exec())
        answer = dialog.answer() if accepted else None
        dialog.deleteLater()
        if answer is not None and answer != location:
            self._set_locations(replaced(self._rows(), answer))

    def _remove_location(self, location_id: str) -> None:
        self._set_locations(without(self._rows(), location_id))

    def _open_location(self, location: Location) -> None:
        QDesktopServices.openUrl(QUrl(location.repository))

    def _choose_location_checkout(self, location: Location) -> None:
        root = self._ask_checkout()
        if root is not None:
            self._record_checkout(root, location.repository)

    def _clone_location(self, location: Location) -> None:
        self._clone(location.repository)

    # -- aiming ---------------------------------------------------------------------------------

    def show_project(self, project_id: NodeId) -> None:
        self._project_id = project_id
        self.code_column.show_message("Reading…")
        self.plan_column.show_message("Reading…")
        self._refresh()
        self._request_logs()

    def project_id(self) -> NodeId | None:
        return self._project_id

    def _project(self) -> Project | None:
        project_id = self._project_id
        if project_id is None or not self._library.has(project_id):
            return None
        return self._library.project(project_id)

    def _refresh(self) -> None:
        project = self._project()
        if project is None:
            return
        facts = self._services.facts_of(project.id)
        self._facts = facts
        self.setWindowTitle(f"{project.title or 'Untitled project'} — Project")
        # Set only what changed: a caret in a field being typed in survives an echo. That
        # is the whole guard — the two fields commit on ``editingFinished``, which setText
        # does not raise, so a refresh cannot write back what it just read.
        if self.name_edit.text() != project.title:
            self.name_edit.setText(project.title)
        if self.summary_edit.text() != project.summary:
            self.summary_edit.setText(project.summary)
        self.code_column.show_facts(code_lines(facts))
        self.plan_column.show_facts(plan_lines(facts))
        self._show_locations()
        self.warning.setText(_warning_text(facts))
        self.warning_row.setVisible(facts.warns)
        # A plan inside its code has no history of its own — the code column already
        # shows it — so the column offers the way out instead of the same commits.
        if facts.state != SEPARATED:
            self.plan_column.show_setup(primary=facts.warns)

    # -- what each column's ⋯ offers -------------------------------------------------------------

    def _busy(self) -> str:
        """Why nothing else can be asked for right now, or ""."""
        return "a request is already out" if self._working else ""

    def _gh_reason(self) -> str:
        """Why a verb that needs the GitHub CLI cannot run right now, or ""."""
        return self._busy() or self._gh_refusal or ""

    def _code_entries(self) -> list[Entry]:
        """The code repository: which code this plan is about, then where it is here."""
        facts = self._facts
        if facts is None:
            return []
        gh = self._gh_reason()
        return [
            RepoAction("Set Code Repository…", code_icon, self._ask_repository),
            RepoAction("Pick from GitHub…", find_icon, self._pick_repository, gh),
            RepoAction(
                "Open on GitHub",
                external_icon,
                self._open_on_github,
                "" if "github.com" in facts.repository else "not a GitHub repository",
            ),
            RepoAction(
                "Create on GitHub…",
                plus_icon,
                self._new_code_repository,
                gh or ("this project already records one" if facts.repository else ""),
            ),
            None,
            RepoAction("Choose Checkout…", folder_icon, self._browse_checkout),
            RepoAction(
                "Clone into Repositories Folder",
                clone_icon,
                self._clone_checkout,
                gh or ("" if facts.repository else "no code repository recorded"),
            ),
        ]

    def _plan_entries(self) -> list[Entry]:
        """The plan repository: where the plan lives, and how it is published."""
        facts = self._facts
        if facts is None:
            return []
        gh = self._gh_reason()
        return [
            RepoAction(
                MOVE_PLAN if facts.state == SEPARATED else SET_UP_PLAN,
                move_icon,
                self._on_move,
                self._busy(),
            ),
            None,
            RepoAction(
                "Publish to GitHub…",
                plus_icon,
                self._publish,
                gh
                or ("already published" if facts.plan_remote else "")
                or ("" if facts.plan_root is not None else "not in a git repository"),
            ),
            RepoAction(
                "Open on GitHub",
                external_icon,
                self._open_plan_on_github,
                "" if "github.com" in facts.plan_remote else "not a GitHub repository",
            ),
        ]

    # -- the logs, read off the GUI thread -------------------------------------------------------

    def _request_logs(self) -> None:
        project = self._project()
        facts = self._facts
        if project is None or facts is None:
            return
        project_id = project.id
        services = self._services
        steps = services.pr_steps(project_id)
        # The older shape keeps plan and code in one repository: its log is the code's.
        code_root = facts.checkout if facts.repository else facts.plan_root
        plan_root = facts.plan_root if facts.state == SEPARATED else None
        plan_scope = ""
        if plan_root is not None:
            directory = services.project_dir(project_id).resolve()
            relative = directory.relative_to(plan_root.resolve())
            plan_scope = relative.as_posix() if relative.parts else ""
        repository = facts.repository

        def body() -> None:  # Worker thread: the captured paths and strings, never the model.
            code = plan = None
            prs: tuple[PullRequest, ...] = ()
            error = ""
            refusal = services.gh_refusal()
            try:
                if code_root is not None:
                    code = services.history_for(code_root, "", LOG_LIMIT)
                if plan_root is not None:
                    plan = services.history_for(plan_root, plan_scope, LOG_LIMIT)
            except (StorageError, OSError) as failure:
                error = str(failure)
            if repository and refusal is None:
                try:
                    prs = tuple(services.open_prs(repository))
                except (StorageError, OSError) as failure:
                    error = error or str(failure)
            self._fetched.emit(_Logs(project_id, code, plan, prs, steps, refusal, error))

        if not self._reader.run("Reading repository logs", body, key="projects.logs"):
            self._refetch = True  # Re-asked when the fetch that is out delivers.

    def _on_logs(self, logs: object) -> None:
        assert isinstance(logs, _Logs)
        if self._refetch:
            self._refetch = False
            self._request_logs()
        if logs.project_id != self._project_id:
            return  # The dialog moved to another project while this fetch was out.
        self._gh_refusal = logs.gh_refusal
        self.gh_note.setText(logs.gh_refusal or "")
        self.gh_note.setVisible(bool(logs.gh_refusal))
        facts = self._facts
        if logs.code is None and logs.error:
            self.code_column.show_message(logs.error)
        else:
            self.code_column.show_log(
                logs.code, logs.prs, logs.steps, empty_text=_code_empty_text(facts)
            )
        if facts is not None and facts.state == SEPARATED:
            if logs.plan is None and logs.error:
                self.plan_column.show_message(logs.error)
            else:
                self.plan_column.show_log(logs.plan)

    # -- edits: through the undo stack, or straight into the library file -------------------------

    def _commit_name(self) -> None:
        project = self._project()
        if project is None:
            return
        text = self.name_edit.text().strip()
        if not text:
            self.name_edit.setText(project.title)  # A project always has a name.
        elif text != project.title:
            self._undo.push(SetFieldCommand(project.id, "title", text, view_origin=self))

    def _commit_summary(self) -> None:
        project = self._project()
        if project is None:
            return
        text = self.summary_edit.text().strip()
        if text != project.summary:
            self._undo.push(SetFieldCommand(project.id, "summary", text, view_origin=self))

    def _code_url(self) -> str:
        """The primary code repository as this mode holds it: the draft's, or the fact
        the project records."""
        primary = primary_code(self._rows())
        return primary.repository if primary is not None else ""

    def _set_repository(self, text: str) -> None:
        """The primary code repository: the draft's first code row, or — through the undo
        stack — the fact the whole team shares, written into ``project.dproj``."""
        if text != self._code_url():
            self._set_locations(_with_code(self._rows(), text))

    def _record_checkout(self, root: Path, repository: str = "") -> None:
        """Where a repository is on this machine: into the draft, or straight into the
        library file — a per-machine fact, so it never goes onto the undo stack. Filed
        under the repository named, else under what the folder is a clone of — its
        origin, or its own path for a repository that has none."""
        key = repository or self._code_url() or origin_url(root) or str(root.resolve())
        if self.mode == CREATE:
            self._draft_checkouts[key] = root
            self._show_locations()
            return
        self._services.set_checkout(key, root)

    def _pick_repository(self) -> None:
        """One of the person's own repositories on GitHub, chosen from the listing rather
        than typed — the same listing a plan repository is cloned from."""
        picker = GhRepoListDialog(
            self._services, self._tasks, self, title="Code Repository", verb="Choose"
        )
        accepted = bool(picker.exec())
        repo = picker.chosen() if accepted else ""
        picker.deleteLater()
        if repo:
            self._set_repository(github_url(repo))

    def _ask_repository(self) -> None:
        facts = self._facts
        if facts is None:
            return
        text = LinePrompt.ask(
            self,
            "Code Repository",
            "The code this plan is about, as git names it",
            "Set",
            text=facts.repository,
            placeholder="https://github.com/acme/widget",
        )
        if text is not None:
            self._set_repository(text)

    def _browse_checkout(self) -> None:
        """A folder on this machine, and the repository it turns out to be.

        A checkout whose origin is not the code repository named is the trap this asks
        about — silently keeping either answer would leave the two disagreeing — and it is
        the same question in both modes, answered into the field or into the library file.
        """
        root = self._ask_checkout()
        if root is None:
            return
        self._record_checkout(root)
        origin = origin_url(root)
        named = self._code_url()
        if not origin or (named and canonical_remote(origin) == canonical_remote(named)):
            return
        if named and not confirm(
            self,
            "Code Repository",
            f"This checkout's origin is {origin}, not {named}.\n\n"
            f"Record {origin} as the code repository?",
            verb="Record",
        ):
            return
        self._set_repository(origin)

    def _ask_checkout(self) -> Path | None:
        """A checkout on this machine: the repository root enclosing whatever folder of
        it was picked, refused in words when the folder is in no repository."""
        start = repositories_folder() or Path.home()
        chosen = QFileDialog.getExistingDirectory(self, "Code Checkout", str(start))
        if not chosen:
            return None
        found = located_folder(Path(chosen))
        if found is None:
            self._say(f"{shown_path(Path(chosen))} is not inside a git repository", "error")
            return None
        return found.root

    def _keep_here(self) -> None:
        project = self._project()
        if project is not None and project.colocation != ACCEPTED:
            self._undo.push(SetFieldCommand(project.id, "colocation", ACCEPTED, view_origin=self))
            self._refresh()

    def _on_move(self) -> None:
        if self._project_id is not None:
            self._move(self._project_id)

    def _open_on_github(self) -> None:
        facts = self._facts
        if facts is not None and facts.repository:
            QDesktopServices.openUrl(QUrl(facts.repository))

    def _open_plan_on_github(self) -> None:
        facts = self._facts
        if facts is not None and facts.plan_remote:
            QDesktopServices.openUrl(QUrl(facts.plan_remote))

    # -- gh, off the GUI thread ---------------------------------------------------------------

    def _clone_checkout(self) -> None:
        """The primary code repository, cloned into the repositories folder."""
        self._clone(self._code_url())

    def _clone(self, url: str) -> None:
        """A repository cloned into the repositories folder — and recorded as this
        machine's checkout of it, into the draft or into the library file."""
        if not url:
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            return
        label = remote_label(url)
        dest = folder / (label.rsplit("/", 1)[-1] or "code")
        if (dest / ".git").exists():
            self._record_checkout(dest, url)
            self._say(f"Using the checkout already at {shown_path(dest)}", "ok")
            return
        if dest.exists():
            self._say(f"{shown_path(dest)} exists and is not a repository", "error")
            return
        services = self._services

        def clone() -> str:
            services.clone(url, dest)
            return str(dest)

        self._cloning = url
        self._work(f"Cloning {label}", "clone", clone, f"Cloning {label} into {shown_path(dest)}…")

    def _new_code_repository(self) -> None:
        project = self._project()
        if project is None:
            return
        name = LinePrompt.ask(
            self,
            "New Code Repository",
            "Repository name on GitHub",
            "Create",
            text=slugify(project.title, fallback="code"),
            placeholder="widget, or acme/widget",
            validate=github_name_problem,
        )
        if name is None:
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            return
        dest = folder / name.rsplit("/", 1)[-1]
        if dest.exists():
            self._say(f"{shown_path(dest)} already exists", "error")
            return
        services = self._services
        self._work(
            f"Creating {name} on GitHub",
            "create",
            lambda: (services.create_repository(name, dest), str(dest)),
            f"Creating {name} on GitHub and cloning it into {shown_path(dest)}…",
        )

    def _publish(self) -> None:
        facts = self._facts
        root = facts.plan_root if facts is not None else None
        if root is None:
            return
        name = LinePrompt.ask(
            self,
            "Publish Plan Repository",
            "Repository name on GitHub",
            "Publish",
            text=root.name,
            placeholder="plans, or acme/plans",
            validate=github_name_problem,
        )
        if name is None:
            return
        services = self._services
        self._work(
            f"Publishing {root.name}",
            "publish",
            lambda: services.publish(root, name),
            f"Publishing {root.name} to GitHub as {name}…",
        )

    def _work(self, label: str, what: str, compute: Callable[[], object], saying: str) -> None:
        def body() -> None:  # Worker thread: only what the closure captured.
            try:
                self._done.emit(what, compute(), "")
            except (StorageError, OSError) as error:
                self._done.emit(what, None, str(error))

        # Said before the body starts: a body that delivers at once (a test's inline
        # runner) must find its outcome the last word, not this. Nothing is pushed at a
        # menu — every entry's reason is computed when the ⋯ opens.
        self._working = True
        self._say(saying, "busy")
        if not self._worker.run(label, body, key=f"projects.{what}"):
            self._working = False
            self._say("Still busy with the last request — try again in a moment", "error")

    def _on_done(self, what: str, result: object, error: str) -> None:
        self._working = False
        if error:
            self._say(error, "error")
            return
        if what == "clone":
            # Recorded the way this mode records a checkout: through the store, which
            # refreshes the columns, or into the draft.
            landed = Path(str(result))
            self._say(f"Cloned into {shown_path(landed)}", "ok")
            self._record_checkout(landed, self._cloning)
            return
        project = self._project()
        if project is None:
            return
        if what == "create":
            assert isinstance(result, tuple)
            url, dest = str(result[0]), Path(str(result[1]))
            self._say(f"Created {remote_label(url)} and cloned it into {shown_path(dest)}", "ok")
            self._push_locations(project, _with_code(project.locations, url))
            self._services.set_checkout(url, dest)
        elif what == "publish":
            self._say(f"Published as {remote_label(str(result))}", "ok")
            self._refresh()
            self._request_logs()

    def _say(self, text: str, tone: Tone = "info") -> None:
        """What the last request came to, in the footer's status slot."""
        self.status.say(text, tone)

    # -- following the model, the store and the theme ----------------------------------------------

    def _on_field(self, node_id: NodeId, field: str, origin: object) -> None:
        if node_id != self._project_id:
            return
        self._refresh()  # Sets only what differs, so an own echo moves no caret.
        if field == "locations" and origin is not self:
            self._request_logs()

    def _on_structure(self, _parent_id: NodeId, _origin: object) -> None:
        if self._project_id is not None and not self._library.has(self._project_id):
            self.close()

    def _on_checkout(self, _repository: str) -> None:
        if self._project_id is not None:
            self._refresh()
            self._request_logs()
        elif self.mode == CREATE:
            self._show_locations()

    def _glyph(self, painter: Callable[[str], QIcon]) -> QLabel:
        """A glyph label that repaints itself on every theme change."""
        label = glyph_label(self)
        self._painters.append(
            lambda ink: label.setPixmap(painter(ink).pixmap(ICON_SIZE, ICON_SIZE))
        )
        return label

    def _paint(self, theme: Theme) -> None:
        """Everything that wears ink, repainted, and the ink itself kept for the pop-ups:
        a menu is built when it opens, from this, so its glyphs cannot go stale."""
        self._ink = theme.text_secondary
        for repaint in self._painters:
            repaint(theme.text_secondary)


def _with_code(locations: tuple[Location, ...], url: str) -> tuple[Location, ...]:
    """The table with its primary code row set to ``url`` — replaced in place, added
    first when there is none, dropped when ``url`` is empty."""
    primary = primary_code(locations)
    if not url:
        return without(locations, primary.id) if primary is not None else locations
    if primary is None:
        return (Location(next_id(locations), CODE.id, url), *locations)
    changed = Location(primary.id, CODE.id, url, primary.path, primary.ref, primary.label)
    return replaced(locations, changed)


def _warning_text(facts: RepositoryFacts) -> str:
    if facts.state == LEGACY:
        return (
            "No code repository is recorded, so the plan reads as living inside the code"
            " it plans — the shape that drifts. Record the code repository, or move the plan."
        )
    return "The plan lives inside the code repository it plans — the shape that drifts."


def _code_empty_text(facts: RepositoryFacts | None) -> str:
    if facts is None:
        return ""
    if facts.repository and facts.checkout is None:
        return "Not checked out on this machine — choose the checkout, or clone it."
    if not facts.repository and facts.plan_root is None:
        return "Not in a git repository."
    return "No commits yet."
