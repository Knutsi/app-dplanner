"""Picking a plan repository: one the library already uses, another folder on disk, a
clone from GitHub — or, where a new one may be made, a fresh local repository or one to
publish on GitHub.

Open Project, Move Plan and New Project all ask this question, so it is one widget: a
dropdown of the known plan repositories, last used first, and one ⋯ menu of the other
ways in — built when it opens, an entry greyed with its reason where it cannot run right
now, the same list to learn in every dialog that asks (DESIGN.md's *Buttons*). What it
answers is a :class:`PlanTarget` — a root, whether it still has to be initialised, and
the GitHub name to publish it under afterwards — and it never touches the model. A clone
runs off the GUI thread and lands in the repositories folder.

:class:`RepoAction`, :func:`menu_of`, :func:`menu_button` and :func:`popup_menu` are the ⋯
vocabulary the Project dialog's repository columns and its code repository field share with
the picker; :func:`tool_button` and :func:`field_row` are the field-and-glyph-button pair
every one of these surfaces is built from; and :class:`GhRepoListDialog` is the listing
they all pick a repository from — to clone here, or to name as the code a plan is about.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.core.storage.locations import find_repo_root, origin_url, remote_label
from dplanner.core.storage.provider import StorageError
from dplanner.framework.dialog import DialogFrame, LinePrompt
from dplanner.framework.signalling import StatusLine, Tone
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.user_config import get_global, set_global
from dplanner.framework.widgets import caption, ink_of
from dplanner.modules.projects.repos import MODULE_ID, RepositoryServices, shown_path
from dplanner.modules.projects.repositories_folder import (
    ensure_repositories_folder,
    repositories_folder,
)
from dplanner.theme.icons import ICON_SIZE, clone_icon, external_icon, folder_icon, plus_icon
from dplanner.theme.tokens import CAPTION_GAP, CONTROL_HEIGHT, FIELD_GAP

LAST_ROOT_KEY = "last_plan_root"
GH_LIST_SIZE = (440, 380)

# The ⋯ button's glyph. A character rather than a painted icon: it names no verb, and every
# platform's font has it.
ELLIPSIS = "⋯"


@dataclass(frozen=True)
class PlanTarget:
    """A plan repository as picked: existing, or a folder still to be made."""

    root: Path
    init: bool = False  # A folder to ``git init`` before use.
    publish: str = ""  # A GitHub name to publish it under once it has a commit.

    @property
    def label(self) -> str:
        if self.init:
            return f"{self.root.name} — new" + (" on GitHub" if self.publish else "")
        origin = origin_url(self.root)
        return remote_label(origin) if origin else self.root.name


@dataclass(frozen=True)
class RepoAction:
    """One entry of a ⋯ menu.

    ``reason`` is what the entry cannot be run for right now, and an entry that has one is
    greyed and carries it — the registry's *disabled, never hidden* rule, applied to a
    pop-up these verbs are too local to reach the registry through. The menu's shape is
    therefore the same whatever the state, which is what makes it learnable.
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


def menu_of(entries: Sequence[Entry], ink: str, parent: QWidget) -> QMenu:
    """A ⋯ menu as it stands: an entry per verb, greyed with its reason where it cannot
    be run. Built afresh every time it opens — a glyph carries the colour it was painted
    in, so a menu kept across a theme change would go stale."""
    menu = QMenu(parent)
    for entry in entries:
        if entry is None:
            menu.addSeparator()
            continue
        action = menu.addAction(entry.icon(ink), entry.text)
        action.setEnabled(not entry.reason)
        action.triggered.connect(lambda _checked=False, run=entry.run: run())
    return menu


def github_name_problem(name: str) -> str | None:
    """Why ``name`` cannot name a repository on GitHub, or None when it can."""
    if re.fullmatch(r"(?:[\w.-]+/)?[\w.-]+", name):
        return None
    return "Letters, digits, dots, dashes and underscores — owner/name picks the owner"


def tool_button(tip: str, name: str, parent: QWidget) -> QToolButton:
    """A glyph button beside a field: the quiet bordered look, the verb in its tooltip,
    and the height of the field it stands beside.

    ``CONTROL_HEIGHT`` each way, set in code for the reason DESIGN.md gives for a strip: a
    glyph button, a worded one and a combo box disagree by pixels under the style — nine of
    them between the ⋯ and the combo it belongs to — and a row whose button is shorter than
    its field reads as two rows. A square is also what centres the glyph.
    """
    button = QToolButton(parent)
    button.setObjectName(name)
    button.setProperty("repoTool", True)
    button.setToolTip(tip)
    button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    button.setFixedSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
    return button


def field_row(field: QWidget, button: QWidget, parent: QWidget) -> QWidget:
    """A field with its glyph button beside it: the field takes the width, the button its
    own square, ``FIELD_GAP`` apart. One row rather than five hand-built ones, which is
    also what keeps the gap the same in every dialog that asks."""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(FIELD_GAP)
    layout.addWidget(field, 1)
    layout.addWidget(button)
    return row


def menu_button(tip: str, parent: QWidget) -> QToolButton:
    """The ⋯ beside a thing, dropping its verbs as a menu of glyph and words."""
    button = tool_button(tip, "RepoMenuButton", parent)
    button.setText(ELLIPSIS)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    return button


def popup_menu(button: QToolButton, entries: Sequence[Entry], ink: str) -> None:
    """Drop a ⋯ button's menu under it, built for this opening and dropped after it — the
    one way every ⋯ in these surfaces opens, so no surface grows a placement of its own."""
    menu = menu_of(entries, ink, button)
    menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
    menu.deleteLater()


class RepoPicker(QWidget):
    changed = QtSignal()
    _cloned = QtSignal(str, str)  # (root, error) — queued from the clone body.

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        *,
        allow_new: bool = False,
        theme: ThemeService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RepoPicker")
        self._services = services
        self._tasks = tasks
        self._theme = theme
        self._allow_new = allow_new
        self._cloning = False
        self._runner = TaskRunner(tasks, parent=self)
        self._cloned.connect(self._on_cloned)
        self._targets: dict[str, PlanTarget] = {}

        self.combo = QComboBox(self)
        self.combo.setObjectName("RepoPickerCombo")
        self.combo.currentIndexChanged.connect(lambda _index: self.changed.emit())
        self.menu_button = menu_button("Other ways to pick a plan repository", self)
        self.menu_button.clicked.connect(self.popup)
        self.note = StatusLine(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(CAPTION_GAP)
        layout.addWidget(field_row(self.combo, self.menu_button, self))
        layout.addWidget(self.note)

        # The repository last picked leads, and is offered even when no library project
        # lives there yet — a browsed-to repository is worth remembering once.
        last = str(get_global(MODULE_ID, LAST_ROOT_KEY, ""))
        roots = services.plan_roots()
        if last and Path(last) not in roots and (Path(last) / ".git").exists():
            roots.insert(0, Path(last))
        for root in sorted(roots, key=lambda root: str(root) != last):
            self._add(PlanTarget(root))

    # -- the answer ------------------------------------------------------------------------

    def current(self) -> PlanTarget | None:
        key = self.combo.currentData()
        return self._targets.get(str(key)) if key else None

    def set_current(self, root: Path) -> None:
        self._add(PlanTarget(root), select=True)

    def remember(self) -> None:
        """Called by the dialog that accepted: the next picker opens on this one."""
        target = self.current()
        if target is not None:
            set_global(MODULE_ID, LAST_ROOT_KEY, str(target.root))

    def _add(self, target: PlanTarget, *, select: bool = False) -> None:
        key = str(target.root)
        if key not in self._targets:
            self.combo.addItem(target.label, key)
        self._targets[key] = target
        if select:
            self.combo.setCurrentIndex(self.combo.findData(key))
            self.changed.emit()

    # -- the ⋯ menu: the other ways in -------------------------------------------------------

    def entries(self) -> list[Entry]:
        """What the menu would offer right now — asked afresh, and what a test reads."""
        busy = "a clone is still running" if self._cloning else ""
        found: list[Entry] = [
            RepoAction("Another folder…", folder_icon, self._browse),
            RepoAction("Clone from GitHub…", clone_icon, self._clone, busy),
        ]
        if self._allow_new:
            found += [
                None,
                RepoAction("New repository here…", plus_icon, self._new_local),
                RepoAction("New repository on GitHub…", external_icon, self._new_github),
            ]
        return found

    def popup(self) -> None:
        popup_menu(self.menu_button, self.entries(), self._ink())

    def _ink(self) -> str:
        """Read when the menu opens, never stored: a pop-up cannot go stale."""
        if self._theme is not None:
            return self._theme.current.text_secondary
        return ink_of(self).name()

    def _browse(self) -> None:
        start = repositories_folder() or Path.home()
        chosen = QFileDialog.getExistingDirectory(self, "Plan Repository", str(start))
        if not chosen:
            return
        root = find_repo_root(Path(chosen))
        if root is None:
            self.say(f"{chosen} is not inside a git repository — clone one, or start a new one")
            return
        self.say("")
        self._add(PlanTarget(root), select=True)

    def _clone(self) -> None:
        picker = GhRepoListDialog(self._services, self._tasks, self)
        accepted = bool(picker.exec())
        repo = picker.chosen() if accepted else ""
        picker.deleteLater()
        if not repo:
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            return
        dest = folder / repo.rsplit("/", 1)[-1]
        if (dest / ".git").exists():
            self._add(PlanTarget(dest), select=True)
            return
        if dest.exists():
            self.say(f"{shown_path(dest)} exists and is not a repository")
            return
        services = self._services

        def body() -> None:
            try:
                services.clone(repo, dest)
                self._cloned.emit(str(dest), "")
            except (StorageError, OSError) as error:
                self._cloned.emit(str(dest), str(error))

        if not self._runner.run(f"Cloning {repo}", body, key="projects.clone"):
            self.say("Another clone is still running")
            return
        self._cloning = True
        self.say(f"Cloning {repo} into {shown_path(dest)}…", "busy")

    def _on_cloned(self, root: str, error: str) -> None:
        self._cloning = False
        if error:
            self.say(error)
            return
        self.say("")
        self._add(PlanTarget(Path(root)), select=True)

    def _new_local(self) -> None:
        start = repositories_folder() or Path.home()
        chosen = QFileDialog.getSaveFileName(
            self,
            "New Plan Repository",
            str(start / "plans"),
            options=QFileDialog.Option.ShowDirsOnly,
        )[0]
        if not chosen:
            return
        path = Path(chosen)
        if path.exists() and any(path.iterdir()):
            self.say(f"{shown_path(path)} is not empty")
            return
        self.say("")
        self._add(PlanTarget(path, init=True), select=True)

    def _new_github(self) -> None:
        name = LinePrompt.ask(
            self,
            "New Plan Repository on GitHub",
            "Repository name on GitHub",
            "Create",
            text="plans",
            validate=github_name_problem,
        )
        if name is None:
            return
        folder = ensure_repositories_folder(self)
        if folder is None:
            return
        path = folder / name.rsplit("/", 1)[-1]
        if path.exists():
            self.say(f"{shown_path(path)} already exists")
            return
        self.say("")
        self._add(PlanTarget(path, init=True, publish=name), select=True)

    def say(self, text: str, tone: Tone = "error") -> None:
        """The line under the picker: a refusal in the error tone, a clone in the busy."""
        self.note.say(text, tone)


def github_listing(services: RepositoryServices) -> tuple[list[str], str]:
    """BLOCKING — the body every listing of the person's GitHub repositories runs on a
    task: the repositories, or why gh could not answer. One body, however many presenters
    (the picking dialog, the location dialog's combo), so a refusal is worded once."""
    refusal = services.gh_refusal()
    if refusal is not None:
        return [], refusal
    try:
        return services.list_repositories(), ""
    except (StorageError, OSError) as error:
        return [], str(error)


class GhRepoListDialog(DialogFrame):
    """The person's GitHub repositories, filtered as they type; one is chosen.

    What the choice is *for* is the caller's — a clone of a plan repository, or the code a
    new plan is about — so the window's name and its primary's verb are given, and the
    dialog itself only lists and answers. The primary is greyed directly rather than
    through ``refuse()``: the footer's status slot is the listing's, busy while gh answers
    and the count or the error afterwards.
    """

    _listed = QtSignal(object, str)  # (repos, error) — queued from the listing body.

    def __init__(
        self,
        services: RepositoryServices,
        tasks: TaskService,
        parent: QWidget | None = None,
        *,
        title: str = "Clone from GitHub",
        verb: str = "Clone",
    ) -> None:
        super().__init__(title, parent, size=GH_LIST_SIZE)
        self._repos: list[str] = []
        self._runner = TaskRunner(tasks, parent=self)
        self._listed.connect(self._on_listed)
        body, layout = self.body, self.body_layout

        form = QVBoxLayout()
        layout.addLayout(form)
        form.setSpacing(CAPTION_GAP)
        form.addWidget(caption("Your repositories", body))
        self.filter_edit = QLineEdit(body)
        self.filter_edit.setObjectName("GhRepoFilter")
        self.filter_edit.setPlaceholderText("Filter…")
        self.filter_edit.textChanged.connect(lambda _text: self._fill())
        form.addWidget(self.filter_edit)
        self.list = QListWidget(body)
        self.list.setObjectName("GhRepoList")
        self.list.itemActivated.connect(lambda _item: self.accept())
        layout.addWidget(self.list, 1)

        self.add_dismiss()
        self.choose_button = self.set_primary(verb, self.accept)
        self.choose_button.setEnabled(False)
        self.list.currentRowChanged.connect(lambda row: self.choose_button.setEnabled(row >= 0))
        self.status.say("Listing your repositories…", "busy")

        self._runner.run(
            "Listing GitHub repositories",
            lambda: self._listed.emit(*github_listing(services)),
            key="projects.gh_list",
        )

    def _on_listed(self, repos: object, error: str) -> None:
        self._repos = [str(repo) for repo in repos] if isinstance(repos, list) else []
        if error:
            self.status.say(error, "error")
        else:
            self.status.say(f"{len(self._repos)} repositories")
        self._fill()

    def _fill(self) -> None:
        needle = self.filter_edit.text().strip().lower()
        self.list.clear()
        for repo in self._repos:
            if needle in repo.lower():
                self.list.addItem(repo)
        if self.list.count():
            self.list.setCurrentRow(0)

    def chosen(self) -> str:
        item = self.list.currentItem()
        return item.text() if item is not None else ""
