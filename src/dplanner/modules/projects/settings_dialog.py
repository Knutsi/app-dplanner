"""The Project dialog: what a project is, where its plan and its code live, and what
both repositories have been up to.

*Project ▸ Settings…* — the settings above a rule, the logs below it in two columns, code
and plan. Every edit above is live and undoable (the name and summary, the code
repository and the colocation go through the undo stack; the checkout is written straight
into the library file, a per-machine fact), so the dialog carries no buttons of its own —
DESIGN.md's rule, the step details dialog the precedent — and one instance serves the
window, re-aimed by ``show_project``.

The logs are read off the GUI thread: one task body reads both histories and the code
repository's open pull requests and hands back one :class:`_Logs`, stamped with the
project it was asked for, so an answer for a project the dialog has since left is dropped.
A pull request row names the step that carries it, when one does — the github aspect's
record, looked up by the composition root — and activating the row opens the PR. Where
the plan has no repository of its own the plan column offers *Set up a plan repository…*
instead of a log: with the accent while the colocation is unaccepted, quiet once it is.
Cloning, publishing and creating on GitHub run in a second task body, and their outcome
lands in the model on the GUI thread through one ``_done`` signal.

*File ▸ New Project…* is the same dialog in **create mode**: the same name, summary, code
repository and checkout fields, the plan repository as a picker with a folder name under
it, no logs, and a Create button. It answers a :class:`NewProjectSpec`; the module seeds
the project and connects it, so the dialog writes nothing anywhere.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QDesktopServices, QIcon
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
    QPushButton,
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
from dplanner.framework.widgets import confirm
from dplanner.modules.projects.repo_picker import PlanTarget, RepoPicker, tool_button
from dplanner.modules.projects.repos import (
    LOG_LIMIT,
    PullRequest,
    RepoLog,
    RepositoryServices,
)
from dplanner.modules.projects.repositories_folder import (
    ensure_repositories_folder,
    repositories_folder,
    shown_path,
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


class RepositoryLogColumn(QWidget):
    """One repository's column: a caption with its branch, then a well of rows — open
    pull requests in bold above the rule, commits below it."""

    activated = QtSignal(str)  # A pull request row's URL.

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = ""
        self.glyph = glyph_label(self)
        self.caption = QLabel(caption, self)
        self.caption.setObjectName("InspectorCaption")
        self.branch = QLabel(self)
        self.branch.setObjectName("LogBranch")
        header = QHBoxLayout()
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
        self.setup_button = QPushButton("Set up a plan repository…", self)
        self.setup_button.setObjectName("PlanSetupButton")
        setup = QWidget(self)
        setup.setObjectName("PlanSetup")
        column = QVBoxLayout(setup)
        column.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.setup_button)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(1)
        self.pages = QStackedWidget(self)
        self.pages.addWidget(self.well)
        self.pages.addWidget(self.empty)
        self.pages.addWidget(setup)
        self.setup = setup

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self.pages, 1)

    def paint(self, painter: Callable[[str], QIcon], color: str) -> None:
        self._color = color
        self.glyph.setPixmap(painter(color).pixmap(ICON_SIZE, ICON_SIZE))

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
        self._loading = False
        self._refetch = False
        self._working = False
        self._reader = TaskRunner(tasks, parent=self)
        self._worker = TaskRunner(tasks, parent=self)
        self._fetched.connect(self._on_logs)
        self._done.connect(self._on_done)

        # -- what the project is, and where its two repositories are ---------------------
        self.project_glyph = glyph_label(self)
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

        self.plan_glyph = glyph_label(self)
        self.plan_label = QLabel(self)
        self.plan_label.setObjectName("PlanRepositoryLabel")
        self.publish_button = QPushButton("Publish to GitHub", self)
        self.publish_button.setObjectName("PublishPlanButton")
        self.publish_button.clicked.connect(self._publish)
        self.move_button = tool_button(
            "Move the plan to a repository of its own", "MovePlanButton", self
        )
        self.move_button.clicked.connect(self._on_move)

        self.code_glyph = glyph_label(self)
        self.repository_combo = QComboBox(self)
        self.repository_combo.setObjectName("CodeRepositoryCombo")
        self.repository_combo.setEditable(True)
        self.repository_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line = self.repository_combo.lineEdit()
        assert line is not None  # An editable combo always has one.
        line.setPlaceholderText("https://github.com/acme/widget — the code this plan is about")
        line.editingFinished.connect(self._commit_repository)
        self.repository_combo.activated.connect(lambda _index: self._commit_repository())
        self.open_button = tool_button("Open on GitHub", "OpenOnGitHubButton", self)
        self.open_button.clicked.connect(self._open_on_github)
        self.new_code_button = tool_button(
            "Create the code repository on GitHub and clone it here",
            "NewCodeRepositoryButton",
            self,
        )
        self.new_code_button.clicked.connect(self._new_code_repository)

        self.checkout_glyph = glyph_label(self)
        self.checkout_edit = QLineEdit(self)
        self.checkout_edit.setObjectName("CodeCheckoutEdit")
        self.checkout_edit.setPlaceholderText("Where the code is checked out on this machine")
        self.checkout_edit.editingFinished.connect(self._commit_checkout)
        self.browse_button = tool_button("Choose the checkout…", "BrowseCheckoutButton", self)
        self.browse_button.clicked.connect(self._browse_checkout)
        self.clone_button = tool_button(
            "Clone into your repositories folder", "CloneCheckoutButton", self
        )
        self.clone_button.clicked.connect(self._clone_checkout)

        self.gh_note = QLabel(self)
        self.gh_note.setObjectName("GhNote")
        self.gh_note.setWordWrap(True)
        self.gh_note.hide()
        self.note = QLabel(self)
        self.note.setObjectName("ProjectNote")
        self.note.setWordWrap(True)
        self.note.hide()
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

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(FIELD_GAP)
        grid.setVerticalSpacing(FIELD_GAP)
        grid.addWidget(self.project_glyph, 0, 0)
        grid.addWidget(self.name_edit, 0, 1, 1, 3)
        grid.addWidget(self.summary_edit, 1, 1, 1, 3)
        grid.addWidget(self.plan_glyph, 2, 0)
        grid.addWidget(self.plan_label, 2, 1)
        grid.addWidget(self.publish_button, 2, 2)
        grid.addWidget(self.move_button, 2, 3)
        grid.addWidget(self.code_glyph, 3, 0)
        grid.addWidget(self.repository_combo, 3, 1)
        grid.addWidget(self.open_button, 3, 2)
        grid.addWidget(self.new_code_button, 3, 3)
        grid.addWidget(self.checkout_glyph, 4, 0)
        grid.addWidget(self.checkout_edit, 4, 1)
        grid.addWidget(self.browse_button, 4, 2)
        grid.addWidget(self.clone_button, 4, 3)
        grid.setColumnStretch(1, 1)
        for row in range(5):
            grid.setRowMinimumHeight(row, ICON_SIZE)
        settings = QWidget(self)
        settings.setObjectName("ProjectSettings")
        column = QVBoxLayout(settings)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(FIELD_GAP)
        column.addLayout(grid)
        column.addWidget(self.gh_note)
        column.addWidget(self.note)
        column.addWidget(self.warning_row)

        # -- what both repositories have been up to ----------------------------------------
        self.code_column = RepositoryLogColumn("Code", self)
        self.code_column.setObjectName("CodeLogColumn")
        self.plan_column = RepositoryLogColumn("Plan", self)
        self.plan_column.setObjectName("PlanLogColumn")
        self.plan_column.setup_button.clicked.connect(self._on_move)
        for log_column in (self.code_column, self.plan_column):
            log_column.activated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        logs = QWidget(self)
        logs.setObjectName("ProjectLogs")
        columns = QHBoxLayout(logs)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(SECTION_GAP)
        columns.addWidget(self.code_column, 1)
        columns.addWidget(self.plan_column, 1)

        rule = card_rule(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        layout.setSpacing(SECTION_GAP)
        layout.addWidget(settings)
        layout.addWidget(rule)
        layout.addWidget(logs, 1)

        # -- create mode: the plan repository is picked, the folder named, nothing edited --
        self.plan_picker: RepoPicker | None = None
        self.folder_edit: QLineEdit | None = None
        self.folder_glyph: QLabel | None = None
        self._folder_touched = False

        self._unsubscribes = [
            library.field_changed.connect(self._on_field),
            library.structure_changed.connect(self._on_structure),
            services.checkout_changed.connect(self._on_checkout),
            theme.changed.connect(self._paint),
        ]
        self._paint(theme.current)
        if mode == CREATE:
            self.setWindowTitle("New Project")
            self.setMinimumSize(520, 360)
            self.resize(640, 420)
            for hidden in (
                self.plan_label,
                self.publish_button,
                self.move_button,
                self.new_code_button,
                self.clone_button,
                rule,
                logs,
            ):
                hidden.hide()
            self.plan_picker = RepoPicker(services, tasks, allow_new=True, theme=theme, parent=self)
            self.plan_picker.setObjectName("PlanRepoPicker")
            self.plan_picker.changed.connect(self._revalidate_create)
            grid.addWidget(self.plan_picker, 2, 1, 1, 3)
            self.folder_glyph = glyph_label(self)
            self.folder_edit = QLineEdit(self)
            self.folder_edit.setObjectName("ProjectFolderEdit")
            self.folder_edit.setPlaceholderText("folder name inside the plan repository")
            self.folder_edit.textEdited.connect(self._folder_typed)
            self.folder_edit.textChanged.connect(lambda _text: self._revalidate_create())
            self.name_edit.textChanged.connect(self._suggest_folder)
            grid.addWidget(self.folder_glyph, 5, 0)
            grid.addWidget(self.folder_edit, 5, 1, 1, 3)
            self.target_label = QLabel(self)
            self.target_label.setObjectName("ProjectFolderPath")
            self.target_label.setWordWrap(True)
            column.addWidget(self.target_label)
            cancel = QPushButton("Cancel", self)
            cancel.clicked.connect(self.reject)
            self.create_button = QPushButton("Create", self)
            self.create_button.setObjectName("PrimaryButton")
            self.create_button.setDefault(True)
            self.create_button.clicked.connect(self.accept)
            footer = QHBoxLayout()
            footer.setSpacing(FIELD_GAP)
            footer.addStretch(1)
            footer.addWidget(cancel)
            footer.addWidget(self.create_button)
            layout.addStretch(1)
            layout.addLayout(footer)
            self._paint(theme.current)
            self._revalidate_create()
            self.name_edit.setFocus()

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
        self._loading = True
        try:
            self.setWindowTitle(f"{project.title or 'Untitled project'} — Project")
            # Set only what changed: a caret in a field being typed in survives an echo.
            if self.name_edit.text() != project.title:
                self.name_edit.setText(project.title)
            if self.summary_edit.text() != project.summary:
                self.summary_edit.setText(project.summary)
            self.plan_label.setText(facts.plan_label or "not in a git repository")
            self.plan_label.setToolTip(str(facts.plan_root or ""))
            self.publish_button.setVisible(facts.plan_root is not None and not facts.plan_remote)
            if self.repository_combo.currentText() != facts.repository:
                self.repository_combo.setEditText(facts.repository)
            shown = shown_path(facts.checkout) if facts.checkout is not None else ""
            if self.checkout_edit.text() != shown:
                self.checkout_edit.setText(shown)
            self.warning.setText(_warning_text(facts))
            self.warning_row.setVisible(facts.warns)
            if facts.state != SEPARATED:
                self.plan_column.show_setup(primary=facts.warns)
        finally:
            self._loading = False
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        facts = self._facts
        if facts is None:
            return
        gh_ok = self._gh_refusal is None and not self._working
        self.open_button.setEnabled("github.com" in facts.repository)
        self.clone_button.setEnabled(bool(facts.repository) and gh_ok)
        self.new_code_button.setEnabled(not facts.repository and gh_ok)
        self.publish_button.setEnabled(gh_ok)
        self.move_button.setEnabled(not self._working)

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
        self._refresh_buttons()

    # -- edits: through the undo stack, or straight into the library file -------------------------

    def _commit_name(self) -> None:
        project = self._project()
        if self._loading or project is None:
            return
        text = self.name_edit.text().strip()
        if not text:
            self.name_edit.setText(project.title)  # A project always has a name.
        elif text != project.title:
            self._undo.push(SetFieldCommand(project.id, "title", text, view_origin=self))

    def _commit_summary(self) -> None:
        project = self._project()
        if self._loading or project is None:
            return
        text = self.summary_edit.text().strip()
        if text != project.summary:
            self._undo.push(SetFieldCommand(project.id, "summary", text, view_origin=self))

    def _commit_repository(self) -> None:
        project = self._project()
        if self._loading or project is None:
            return
        text = self.repository_combo.currentText().strip()
        if text != project.repository:
            self._undo.push(SetFieldCommand(project.id, "repository", text, view_origin=self))
            self._refresh()
            self._request_logs()

    def _commit_checkout(self) -> None:
        project = self._project()
        facts = self._facts
        if self._loading or project is None or facts is None:
            return
        text = self.checkout_edit.text().strip()
        path = Path(text).expanduser() if text else None
        if path != facts.checkout:
            self._services.set_checkout(project.id, path)

    def _browse_checkout(self) -> None:
        project = self._project()
        if project is None and self.mode != CREATE:
            return
        start = repositories_folder() or Path.home()
        chosen = QFileDialog.getExistingDirectory(self, "Code Checkout", str(start))
        if not chosen:
            return
        root = find_repo_root(Path(chosen)) or Path(chosen)
        origin = origin_url(root)
        if self.mode == CREATE:  # Nothing exists yet: the fields carry the answer to Create.
            self.checkout_edit.setText(shown_path(root))
            if origin and not self.repository_combo.currentText().strip():
                self.repository_combo.setEditText(origin)
            return
        assert project is not None
        self._services.set_checkout(project.id, root)
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
        self._undo.push(SetFieldCommand(project.id, "repository", origin, view_origin=self))
        self._refresh()
        self._request_logs()

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
        # runner) must find its outcome the last word, not this.
        self._working = True
        self._say(saying)
        self._refresh_buttons()
        if not self._worker.run(label, body, key=f"projects.{what}"):
            self._working = False
            self._say("Still busy with the last request — try again in a moment")
            self._refresh_buttons()

    def _on_done(self, what: str, result: object, error: str) -> None:
        self._working = False
        project = self._project()
        if error:
            self._say(error)
            self._refresh_buttons()
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

    def _paint(self, theme: Theme) -> None:
        color = theme.text_secondary
        glyphs = (
            (self.project_glyph, project_icon),
            (self.plan_glyph, branch_icon),
            (self.code_glyph, code_icon),
            (self.checkout_glyph, folder_icon),
        )
        for label, painter in glyphs:
            label.setPixmap(painter(color).pixmap(ICON_SIZE, ICON_SIZE))
        if self.folder_glyph is not None:
            self.folder_glyph.setPixmap(container_icon(color).pixmap(ICON_SIZE, ICON_SIZE))
        self.move_button.setIcon(move_icon(color))
        self.open_button.setIcon(external_icon(color))
        self.new_code_button.setIcon(plus_icon(color))
        self.browse_button.setIcon(folder_icon(color))
        self.clone_button.setIcon(clone_icon(color))
        self.code_column.paint(code_icon, color)
        self.plan_column.paint(branch_icon, color)


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
