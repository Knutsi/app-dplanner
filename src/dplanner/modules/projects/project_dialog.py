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
file, a per-machine fact), so the dialog carries no buttons of its own — DESIGN.md's rule,
the step details dialog the precedent — and one instance serves the window, re-aimed by
``show_project``.

The logs are read off the GUI thread: one task body reads both histories and the code
repository's open pull requests and hands back one :class:`_Logs`, stamped with the
project it was asked for, so an answer for a project the dialog has since left is dropped.
A pull request row names the step that carries it, when one does — the github aspect's
record, looked up by the composition root — and activating the row opens the PR. Where
the plan has no repository of its own the plan column offers *Set up a plan repository…*
instead of a log: its history *is* the code's, and showing the same commits twice would
say they were apart. Cloning, publishing and creating on GitHub run in a second task body,
and their outcome lands in the model on the GUI thread through one ``_done`` signal.

*File ▸ New Project…* is the same dialog in **create mode**: a form, because nothing
exists yet to have a menu about — the name, the summary, the plan repository as a picker
with a folder name under it, the code repository and its checkout as fields, and a Create
button. It answers a :class:`NewProjectSpec`; the module seeds the project and connects
it, so the dialog writes nothing anywhere.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.fsio import slugify
from dplanner.core.storage.locations import (
    canonical_remote,
    find_repo_root,
    origin_url,
    remote_label,
)
from dplanner.core.storage.provider import StorageError
from dplanner.domain.commands import SetFieldCommand
from dplanner.domain.model import Library, NodeId, Project
from dplanner.domain.plan_repo import ago
from dplanner.domain.repositories import ACCEPTED, LEGACY, SEPARATED, RepositoryFacts
from dplanner.framework.cards import card_rule
from dplanner.framework.list_rows import (
    DETAIL_ROLE,
    EMPHASIS_ROLE,
    RULE_ROLE,
    TwoLineDelegate,
)
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.undo import UndoService
from dplanner.framework.undo_keys import install_undo_keys
from dplanner.framework.widgets import confirm
from dplanner.modules.projects.repo_picker import PlanTarget, RepoPicker, tool_button
from dplanner.modules.projects.repos import (
    LOG_LIMIT,
    MOVE_PLAN,
    SET_UP_PLAN,
    PullRequest,
    RepoLines,
    RepoLog,
    RepositoryServices,
    code_lines,
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
    container_icon,
    external_icon,
    folder_icon,
    move_icon,
    plus_icon,
    project_icon,
    pull_request_icon,
)
from dplanner.theme.themes import Theme

DIALOG_MARGIN = 20
SECTION_GAP = 12
FIELD_GAP = 8
URL_ROLE = int(Qt.ItemDataRole.UserRole) + 10

SETTINGS = "settings"
CREATE = "create"

# The ⋯ button's glyph. A character rather than a painted icon: it names no verb, and every
# platform's font has it.
ELLIPSIS = "\u22ef"


@dataclass(frozen=True)
class NewProjectSpec:
    """What Create asked for — seeded and connected by the module, never by the dialog."""

    title: str
    summary: str
    plan: PlanTarget
    folder: str
    repository: str
    checkout: Path | None

    @property
    def target(self) -> Path:
        return self.plan.root / self.folder


@dataclass(frozen=True)
class RepoAction:
    """One entry of a column's ⋯ menu.

    ``reason`` is what the entry cannot be run for right now, and an entry that has one is
    greyed and carries it — the registry's *disabled, never hidden* rule, applied to a
    pop-up these verbs are too local to reach the registry through. The menu's shape is
    therefore the same whatever the project's state, which is what makes it learnable.
    """

    label: str
    icon: Callable[[str], QIcon]
    run: Callable[[], None]
    reason: str = ""

    @property
    def text(self) -> str:
        return f"{self.label} — {self.reason}" if self.reason else self.label


# A None entry parts two groups of verbs inside one menu.
Entry = RepoAction | None


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
    which is the shape behind CLAUDE.md's synchronous-layout crash. Painting cannot.
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

    def __init__(
        self,
        caption: str,
        entries: Callable[[], Sequence[Entry]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._color = ""
        self._entries = entries
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # A child layout joins its parent before it is filled: a parentless one leaves the
        # item wrappers it was given alive on the Python side (CLAUDE.md's layout rules).
        header = QHBoxLayout()
        layout.addLayout(header)
        self.glyph = glyph_label(self)
        self.caption = QLabel(caption, self)
        self.caption.setObjectName("InspectorCaption")
        self.branch = QLabel(self)
        self.branch.setObjectName("LogBranch")
        header.setSpacing(6)
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
        self.empty = QLabel(self)
        self.empty.setObjectName("LogEmpty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.setup_button = QPushButton(SET_UP_PLAN, self)
        self.setup_button.setObjectName("PlanSetupButton")
        setup = QWidget(self)
        setup.setObjectName("PlanSetup")
        column = QVBoxLayout(setup)
        row = QHBoxLayout()
        column.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        row.addStretch(1)
        row.addWidget(self.setup_button)
        row.addStretch(1)
        self.pages = QStackedWidget(self)
        self.pages.addWidget(self.well)
        self.pages.addWidget(self.empty)
        self.pages.addWidget(setup)
        self.setup = setup
        layout.addWidget(self.pages, 1)

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
        self.menu_button = tool_button(
            f"What you can do with the {caption.lower()} repository", "RepoMenuButton", self
        )
        self.menu_button.setText(ELLIPSIS)
        self.menu_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.menu_button.clicked.connect(self.popup)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setHorizontalSpacing(FIELD_GAP)
        footer.setVerticalSpacing(2)
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
            self.pages.setCurrentWidget(self.well)
        else:
            self.show_message(empty_text)

    def show_message(self, text: str) -> None:
        self.empty.setText(text)
        self.pages.setCurrentWidget(self.empty)

    def show_setup(self, *, primary: bool) -> None:
        restyle(self.setup_button, "PrimaryButton" if primary else "PlanSetupButton")
        self.branch.setText("")
        self.pages.setCurrentWidget(self.setup)

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

    def menu(self) -> QMenu:
        """The ⋯ menu as it stands: an entry per verb, greyed with its reason where it
        cannot be run. Built afresh every time — a glyph carries the colour it was painted
        in, so a menu kept across a theme change would go stale."""
        menu = QMenu(self)
        for entry in self.entries():
            if entry is None:
                menu.addSeparator()
                continue
            action = menu.addAction(entry.icon(self._color), entry.text)
            action.setEnabled(not entry.reason)
            action.triggered.connect(lambda _checked=False, run=entry.run: run())
        return menu

    def popup(self) -> None:
        menu = self.menu()
        menu.exec(self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft()))
        menu.deleteLater()

    def _activate(self, item: QListWidgetItem) -> None:
        url = item.data(URL_ROLE)
        if url:
            self.activated.emit(str(url))


class ProjectDialog(QDialog):
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
        super().__init__(parent)
        self.setObjectName("ProjectDialog")
        self.setWindowTitle("Project")
        install_undo_keys(self, undo)
        self.setMinimumSize(560, 460)
        self.resize(780, 640)
        self.mode = mode
        self._library = library
        self._undo = undo
        self._services = services
        self._move = move
        self._project_id: NodeId | None = None
        self._facts: RepositoryFacts | None = None
        self._gh_refusal: str | None = None
        self._refetch = False
        self._working = False
        self._reader = TaskRunner(tasks, parent=self)
        self._worker = TaskRunner(tasks, parent=self)
        # Everything that wears the theme's ink, as "repaint me in this colour". A mode
        # adds what it built, so _paint branches on nothing.
        self._painters: list[Callable[[str], None]] = []
        self._fetched.connect(self._on_logs)
        self._done.connect(self._on_done)

        # -- what the project is ---------------------------------------------------------
        self.project_glyph = self._glyph(project_icon)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("ProjectNameEdit")
        self.name_edit.setPlaceholderText("What this project is called")
        font = self.name_edit.font()
        font.setPointSize(font.pointSize() + 2)
        self.name_edit.setFont(font)
        self.name_edit.editingFinished.connect(self._commit_name)
        self.summary_edit = QLineEdit(self)
        self.summary_edit.setObjectName("ProjectSummaryEdit")
        self.summary_edit.setPlaceholderText("What it delivers, in one line")
        self.summary_edit.editingFinished.connect(self._commit_summary)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.setSpacing(SECTION_GAP)
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

        # -- one column per repository, parted by the divide that says they are two -------
        self.code_column = RepositoryColumn("Code", self._code_entries, self)
        self.code_column.setObjectName("CodeLogColumn")
        self.plan_column = RepositoryColumn("Plan", self._plan_entries, self)
        self.plan_column.setObjectName("PlanLogColumn")
        self._painters.append(lambda ink: self.code_column.paint(code_icon, ink))
        self._painters.append(lambda ink: self.plan_column.paint(branch_icon, ink))
        self.plan_column.setup_button.clicked.connect(self._on_move)
        for log_column in (self.code_column, self.plan_column):
            log_column.activated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        logs = QWidget(self)
        logs.setObjectName("ProjectLogs")
        columns = QHBoxLayout(logs)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(SECTION_GAP)
        columns.addWidget(self.code_column, 1)
        columns.addWidget(card_rule(logs, vertical=True))
        columns.addWidget(self.plan_column, 1)

        # -- what is wrong, and what the last request did ---------------------------------
        self.warning = QLabel(self)
        self.warning.setObjectName("ColocationWarningText")
        self.warning.setWordWrap(True)
        self.keep_button = QPushButton("Keep it here", self)
        self.keep_button.setObjectName("KeepColocationButton")
        self.keep_button.setToolTip("The plan stays inside its code on purpose; stop warning")
        self.keep_button.clicked.connect(self._keep_here)
        self.warning_row = QWidget(self)
        self.warning_row.setObjectName("ColocationWarning")
        warning_layout = QHBoxLayout(self.warning_row)
        warning_layout.setContentsMargins(0, 0, 0, 0)
        warning_layout.setSpacing(FIELD_GAP)
        warning_layout.addWidget(self.warning, 1)
        warning_layout.addWidget(self.keep_button)
        self.gh_note = QLabel(self)
        self.gh_note.setObjectName("GhNote")
        self.gh_note.setWordWrap(True)
        self.gh_note.hide()
        self.note = QLabel(self)
        self.note.setObjectName("ProjectNote")
        self.note.setWordWrap(True)
        self.note.hide()

        rule = card_rule(self)
        layout.addWidget(rule)
        layout.addWidget(logs, 1)
        layout.addWidget(self.warning_row)
        layout.addWidget(self.gh_note)
        layout.addWidget(self.note)

        # -- create mode: a form, because there is nothing yet to have a menu about -------
        self.plan_picker: RepoPicker | None = None
        self.folder_edit: QLineEdit | None = None
        self.repository_combo: QComboBox | None = None
        self.checkout_edit: QLineEdit | None = None
        self._folder_touched = False

        self._unsubscribes = [
            library.field_changed.connect(self._on_field),
            library.structure_changed.connect(self._on_structure),
            services.checkout_changed.connect(self._on_checkout),
            theme.changed.connect(self._paint),
        ]
        self._paint(theme.current)
        if mode == CREATE:
            self._build_create_form(grid, layout, rule, logs, services, tasks, theme)

    def _build_create_form(
        self,
        grid: QGridLayout,
        layout: QVBoxLayout,
        rule: QWidget,
        logs: QWidget,
        services: RepositoryServices,
        tasks: TaskService,
        theme: ThemeService,
    ) -> None:
        """New Project…: the same name and summary, then the fields that decide where the
        plan and the code will live. No logs and no menus — nothing exists to read or act
        on yet — so the answer is a :class:`NewProjectSpec` and a Create button."""
        self.setWindowTitle("New Project")
        self.setMinimumSize(520, 360)
        self.resize(640, 420)
        for hidden in (rule, logs, self.warning_row):
            hidden.hide()

        self.plan_picker = RepoPicker(services, tasks, allow_new=True, theme=theme, parent=self)
        self.plan_picker.setObjectName("PlanRepoPicker")
        self.plan_picker.changed.connect(self._revalidate_create)
        self.plan_glyph = self._glyph(branch_icon)
        self.folder_glyph = self._glyph(container_icon)
        self.folder_edit = QLineEdit(self)
        self.folder_edit.setObjectName("ProjectFolderEdit")
        self.folder_edit.setPlaceholderText("folder name inside the plan repository")
        self.folder_edit.textEdited.connect(self._folder_typed)
        self.folder_edit.textChanged.connect(lambda _text: self._revalidate_create())
        self.name_edit.textChanged.connect(self._suggest_folder)

        self.code_glyph = self._glyph(code_icon)
        self.repository_combo = QComboBox(self)
        self.repository_combo.setObjectName("CodeRepositoryCombo")
        self.repository_combo.setEditable(True)
        self.repository_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line = self.repository_combo.lineEdit()
        assert line is not None  # An editable combo always has one.
        line.setPlaceholderText("https://github.com/acme/widget — the code this plan is about")
        self.checkout_glyph = self._glyph(folder_icon)
        self.checkout_edit = QLineEdit(self)
        self.checkout_edit.setObjectName("CodeCheckoutEdit")
        self.checkout_edit.setPlaceholderText("Where the code is checked out on this machine")
        self.browse_button = tool_button("Choose the checkout…", "BrowseCheckoutButton", self)
        self.browse_button.clicked.connect(self._browse_for_create)
        self._painters.append(lambda ink: self.browse_button.setIcon(folder_icon(ink)))

        grid.addWidget(self.plan_glyph, 2, 0)
        grid.addWidget(self.plan_picker, 2, 1, 1, 2)
        grid.addWidget(self.folder_glyph, 3, 0)
        grid.addWidget(self.folder_edit, 3, 1, 1, 2)
        grid.addWidget(self.code_glyph, 4, 0)
        grid.addWidget(self.repository_combo, 4, 1, 1, 2)
        grid.addWidget(self.checkout_glyph, 5, 0)
        grid.addWidget(self.checkout_edit, 5, 1)
        grid.addWidget(self.browse_button, 5, 2)
        for row in range(2, 6):
            grid.setRowMinimumHeight(row, ICON_SIZE)

        self.target_label = QLabel(self)
        self.target_label.setObjectName("ProjectFolderPath")
        self.target_label.setWordWrap(True)
        footer = QHBoxLayout()
        layout.addWidget(self.target_label)
        layout.addStretch(1)
        layout.addLayout(footer)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        self.create_button = QPushButton("Create", self)
        self.create_button.setObjectName("PrimaryButton")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self.accept)
        footer.setSpacing(FIELD_GAP)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.create_button)
        self._paint(theme.current)
        self._revalidate_create()
        self.name_edit.setFocus()

    # -- create mode ---------------------------------------------------------------------------

    def spec(self) -> NewProjectSpec | None:
        """What Create would make; None while a name, a plan repository or a folder is
        missing."""
        if self.plan_picker is None or self.folder_edit is None:
            return None
        assert self.checkout_edit is not None and self.repository_combo is not None
        title = self.name_edit.text().strip()
        plan = self.plan_picker.current()
        folder = self.folder_edit.text().strip()
        if not title or plan is None or not folder:
            return None
        checkout = self.checkout_edit.text().strip()
        return NewProjectSpec(
            title=title,
            summary=self.summary_edit.text().strip(),
            plan=plan,
            folder=folder,
            repository=self.repository_combo.currentText().strip(),
            checkout=Path(checkout).expanduser() if checkout else None,
        )

    def _folder_typed(self, _text: str) -> None:
        self._folder_touched = True  # From here the name no longer dictates the folder.

    def _suggest_folder(self, title: str) -> None:
        if self.folder_edit is not None and not self._folder_touched:
            self.folder_edit.setText(slugify(title, fallback="project") if title.strip() else "")

    def _revalidate_create(self) -> None:
        if self.mode != CREATE:
            return
        spec = self.spec()
        if spec is None:
            self.target_label.setText("")
            self.create_button.setEnabled(False)
            return
        exists = spec.target.exists()
        self.target_label.setText(shown_path(spec.target) + (" — already exists" if exists else ""))
        self.create_button.setEnabled(not exists)

    def accept(self) -> None:
        if self.plan_picker is not None:
            self.plan_picker.remember()
        super().accept()

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

    def _set_repository(self, text: str) -> None:
        """The code repository, through the undo stack — it is a fact the whole team
        shares, written into ``project.dproj``."""
        project = self._project()
        if project is None or text == project.repository:
            return
        self._undo.push(SetFieldCommand(project.id, "repository", text, view_origin=self))
        self._refresh()
        self._request_logs()

    def _ask_repository(self) -> None:
        facts = self._facts
        if facts is None:
            return
        text, ok = QInputDialog.getText(
            self,
            "Code Repository",
            "The code this plan is about, as git names it:",
            text=facts.repository,
        )
        if ok:
            self._set_repository(text.strip())

    def _browse_checkout(self) -> None:
        """Where the code is on this machine — a per-machine fact, so it goes straight
        into the library file rather than onto the undo stack."""
        project = self._project()
        if project is None:
            return
        root = self._ask_checkout()
        if root is None:
            return
        self._services.set_checkout(project.id, root)
        origin = origin_url(root)
        if not origin:
            return
        if project.repository and canonical_remote(origin) == canonical_remote(project.repository):
            return
        if project.repository and not confirm(
            self,
            "Code Repository",
            f"This checkout's origin is {origin}, not {project.repository}.\n\n"
            f"Record {origin} as the code repository?",
        ):
            return
        self._set_repository(origin)

    def _browse_for_create(self) -> None:
        """Create mode: nothing exists yet, so a picked checkout fills the fields that
        carry the answer to Create rather than writing anything."""
        root = self._ask_checkout()
        if root is None or self.checkout_edit is None or self.repository_combo is None:
            return
        self.checkout_edit.setText(shown_path(root))
        origin = origin_url(root)
        if origin and not self.repository_combo.currentText().strip():
            self.repository_combo.setEditText(origin)

    def _ask_checkout(self) -> Path | None:
        start = repositories_folder() or Path.home()
        chosen = QFileDialog.getExistingDirectory(self, "Code Checkout", str(start))
        if not chosen:
            return None
        return find_repo_root(Path(chosen)) or Path(chosen)

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
        facts = self._facts
        project = self._project()
        if project is None or facts is None or not facts.repository:
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            return
        url = facts.repository
        label = remote_label(url)
        dest = folder / (label.rsplit("/", 1)[-1] or "code")
        if (dest / ".git").exists():
            self._services.set_checkout(project.id, dest)
            self._say(f"Using the checkout already at {shown_path(dest)}")
            return
        if dest.exists():
            self._say(f"{shown_path(dest)} exists and is not a repository")
            return
        services = self._services

        def clone() -> str:
            services.clone(url, dest)
            return str(dest)

        self._work(f"Cloning {label}", "clone", clone, f"Cloning {label} into {shown_path(dest)}…")

    def _new_code_repository(self) -> None:
        project = self._project()
        if project is None:
            return
        name, ok = QInputDialog.getText(
            self,
            "New Code Repository",
            "Repository name on GitHub:",
            text=slugify(project.title, fallback="code"),
        )
        name = name.strip()
        if not ok or not name:
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            return
        dest = folder / name.rsplit("/", 1)[-1]
        if dest.exists():
            self._say(f"{shown_path(dest)} already exists")
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
        name, ok = QInputDialog.getText(
            self, "Publish Plan Repository", "Repository name on GitHub:", text=root.name
        )
        name = name.strip()
        if not ok or not name:
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
        self._say(saying)
        if not self._worker.run(label, body, key=f"projects.{what}"):
            self._working = False
            self._say("Still busy with the last request — try again in a moment")

    def _on_done(self, what: str, result: object, error: str) -> None:
        self._working = False
        project = self._project()
        if error:
            self._say(error)
            return
        if project is None:
            return
        if what == "clone":
            landed = Path(str(result))
            self._say(f"Cloned into {shown_path(landed)}")
            self._services.set_checkout(project.id, landed)  # Refreshes through the store.
        elif what == "create":
            assert isinstance(result, tuple)
            url, dest = str(result[0]), Path(str(result[1]))
            self._say(f"Created {remote_label(url)} and cloned it into {shown_path(dest)}")
            self._undo.push(SetFieldCommand(project.id, "repository", url, view_origin=self))
            self._services.set_checkout(project.id, dest)
        elif what == "publish":
            self._say(f"Published as {remote_label(str(result))}")
            self._refresh()
            self._request_logs()

    def _say(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    # -- following the model, the store and the theme ----------------------------------------------

    def _on_field(self, node_id: NodeId, field: str, origin: object) -> None:
        if node_id != self._project_id:
            return
        self._refresh()  # Sets only what differs, so an own echo moves no caret.
        if field == "repository" and origin is not self:
            self._request_logs()

    def _on_structure(self, _parent_id: NodeId, _origin: object) -> None:
        if self._project_id is not None and not self._library.has(self._project_id):
            self.close()

    def _on_checkout(self, project_id: str) -> None:
        if project_id == self._project_id:
            self._refresh()
            self._request_logs()

    def _glyph(self, painter: Callable[[str], QIcon]) -> QLabel:
        """A glyph label that repaints itself on every theme change."""
        label = glyph_label(self)
        self._painters.append(
            lambda ink: label.setPixmap(painter(ink).pixmap(ICON_SIZE, ICON_SIZE))
        )
        return label

    def _paint(self, theme: Theme) -> None:
        """Everything that wears ink, repainted. The menus' glyphs are not here: a pop-up
        is built when it opens, so its colour cannot go stale."""
        for repaint in self._painters:
            repaint(theme.text_secondary)


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
