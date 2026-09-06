"""The GitHub tab: the branch and PR a step lands in, typed or picked — and where they
stand right now.

Both fields are editable combos so recording works with no ``gh`` and no network — the
pickers are the enhancement, filled from GitHub in the background when the library has a
repository URL and ``gh`` can be used. Merged and closed PRs stay in the list, marked, so
a step can be pointed at work that already landed.

**The same fetch is the tab's status.** Showing a step asks GitHub for the repository's
branches and PRs (again, once the last answer is older than :data:`LISTS_TTL_S`), and the
answer says two things a person opens the tab to learn: the PR's state and title as they
are now, and whether the branch is still on the remote — a branch gone after its merge
is how a finished step reads finished. Fresh PR state is written into the step the way
the background refresher writes it (directly, with its origin), so the card's pill and
the CLI see what the tab saw. *Open PR* and *Open branch* hand the URLs to the browser.
"""

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Step, StepId
from dplanner.framework.module_data_section import (
    FIELD_GAP,
    FORM_SPACING,
    PANEL_MARGIN,
    ModuleDataSection,
)
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.undo import UndoService
from dplanner.modules.github.aspect import (
    MODULE_ID,
    GithubRefs,
    branch_url,
    pr_label,
    pr_url,
    read,
    refreshed,
    write,
)
from dplanner.modules.github.gh import (
    GhError,
    PrInfo,
    gh_refusal,
    list_branches,
    list_prs,
    parse_repo,
    pr_number_from,
)
from dplanner.modules.github.refresh import REFRESH_ORIGIN
from dplanner.theme.icons import external_icon

# Green for a merged check, red for a closed cross: the same low-alpha-tint family as the
# canvas (DESIGN.md exception #2), opaque here because it colours text, not a region.
MERGED_COLOUR = QColor(110, 180, 130)
CLOSED_COLOUR = QColor(200, 110, 110)

STATE_MARKS = {"merged": "✓ merged", "closed": "✗ closed"}

# How long a fetched answer serves before showing a step asks GitHub again.
LISTS_TTL_S = 60.0


def open_url(url: str) -> None:
    """Hand a URL to the browser — one seam, so a test can watch instead."""
    QDesktopServices.openUrl(QUrl(url))


class GithubSection(ModuleDataSection):
    # Worker → GUI: one fetch's result, queued because it is emitted off-thread.
    _fetched = QtSignal(str, object, object, str)  # (repo, branches, prs, message)

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        repository_for: Callable[[StepId], str],
        tasks: TaskService,
    ) -> None:
        super().__init__(library, undo, module_id=MODULE_ID, undo_label="Set GitHub Refs")
        self._repository_for = repository_for
        self._runner = TaskRunner(tasks, parent=self)
        self._prs: dict[int, PrInfo] = {}
        self._branches: set[str] | None = None  # None until a fetch has answered.
        # Which repo the pickers were (or are being) fetched for, and when the answer
        # came. Projects can carry their own repository, so showing a step from another
        # project may mean a refetch; so does an answer older than the TTL.
        self._loaded_repo: str | None = None
        self._loaded_at = 0.0
        self._fetching = False
        self._fetched.connect(self._on_lists)

        layout = QFormLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(FORM_SPACING)

        self.branch_edit = QComboBox(self)
        self.pr_edit = QComboBox(self)
        self._lines: list[QLineEdit] = []
        placeholders = {self.branch_edit: "feat/login", self.pr_edit: "#12, or the PR's URL"}
        for combo, placeholder in placeholders.items():
            combo.setEditable(True)
            line = combo.lineEdit()
            assert line is not None  # Editable combo always has one.
            line.setPlaceholderText(placeholder)
            line.editingFinished.connect(self.commit)
            combo.activated.connect(lambda _index: self.commit())
            self._lines.append(line)
        layout.addRow("Branch", self.branch_edit)
        layout.addRow("Pull request", self.pr_edit)

        # Where they stand: the PR's live state and title, the branch's presence on the
        # remote, and the way out to each in the browser.
        self.open_pr = self._open_button("Open PR", "Open the pull request in the browser")
        self.open_pr.clicked.connect(lambda: self._open(self._pr_link()))
        self.open_branch = self._open_button("Open branch", "Open the branch on GitHub")
        self.open_branch.clicked.connect(lambda: self._open(self._branch_link()))
        links = QWidget(self)
        links_row = QHBoxLayout(links)
        links_row.setContentsMargins(0, 0, 0, 0)
        links_row.setSpacing(FIELD_GAP)
        links_row.addWidget(self.open_pr)
        links_row.addWidget(self.open_branch)
        links_row.addStretch(1)
        layout.addRow(links)
        self.standing = QLabel(self)
        self.standing.setObjectName("InspectorNote")
        self.standing.setWordWrap(True)
        layout.addRow(self.standing)

        self.status = QLabel(self)
        self.status.setObjectName("InspectorNote")
        self.status.setWordWrap(True)
        layout.addRow(self.status)

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)
        self._request_lists()
        self._show_standing()

    def _open_button(self, label: str, tip: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("ToolbarButton")
        button.setText(label)
        button.setToolTip(tip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIcon(external_icon(self.palette().text().color().name()))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    # -- the pickers -----------------------------------------------------------------------

    def _repo(self) -> str | None:
        step = self.step()
        return parse_repo(self._repository_for(step.id)) if step is not None else None

    def _request_lists(self) -> None:
        """Start a background fetch for the shown step's repository, when it needs one.

        A step with no parseable GitHub repository never spawns a subprocess — which is
        also what keeps a test building the real panel deterministic. An answer younger
        than the TTL still serves; an older one is asked for again, which is what makes
        the standing line current when the tab is opened.
        """
        if self.step() is None:
            return
        repo = self._repo()
        if repo is None:
            self.status.setText(
                "Set the project's code repository (Project ▸ Settings…) to list branches and PRs"
            )
            return
        if repo == self._loaded_repo and (
            self._fetching or time.monotonic() - self._loaded_at < LISTS_TTL_S
        ):
            return

        def body() -> None:  # Worker thread: only the captured repo string, never the model.
            refusal = gh_refusal(check_auth=True)
            if refusal is not None:
                self._fetched.emit(repo, [], [], refusal)
                return
            try:
                self._fetched.emit(repo, list_branches(repo), list_prs(repo), "")
            except GhError as error:
                self._fetched.emit(repo, [], [], str(error))

        # False when a fetch for another repo is still out — its delivery below re-runs
        # this request, so the shown step's repo is picked up when the runner frees.
        if self._runner.run("Listing branches and PRs", body, key="github.pickers"):
            if repo != self._loaded_repo:
                self._prs, self._branches = {}, None  # Another repository's answers.
            self._loaded_repo = repo
            self._fetching = True
            self.status.setText("Fetching branches and PRs…")
            self.status.show()

    def _on_lists(self, repo: str, branches: object, prs: object, message: str) -> None:
        branch_names = branches if isinstance(branches, list) else []
        pr_infos = prs if isinstance(prs, list) else []
        if repo != self._loaded_repo:
            return  # The shown step moved to another repo while this fetch was out.
        self._fetching = False
        if message:
            self._loaded_at = 0.0  # Nothing learned: ask again on the next show.
            self.status.setText(f"{message} — type values manually")
            self._show_standing()
            return
        self._loaded_at = time.monotonic()
        self.status.setText("")
        self.status.hide()
        self._prs = {pr.number: pr for pr in pr_infos}
        self._branches = set(branch_names)
        # Repopulating must not commit a transient value.
        for combo in (self.branch_edit, self.pr_edit):
            combo.blockSignals(True)
        current_branch, current_pr = self.branch_edit.currentText(), self.pr_edit.currentText()
        self.branch_edit.clear()
        self.branch_edit.addItems(branch_names)
        self.pr_edit.clear()
        for index, pr in enumerate(pr_infos):
            mark = STATE_MARKS.get(pr.state, "")
            self.pr_edit.addItem(f"#{pr.number}  {pr.title}" + (f"  {mark}" if mark else ""))
            colour = {"merged": MERGED_COLOUR, "closed": CLOSED_COLOUR}.get(pr.state)
            if colour is not None:
                role = Qt.ItemDataRole.ForegroundRole
                self.pr_edit.setItemData(index, QBrush(colour), role)
        self.branch_edit.setEditText(current_branch)
        self.pr_edit.setEditText(current_pr)
        for combo in (self.branch_edit, self.pr_edit):
            combo.blockSignals(False)
        self._adopt_fresh_state()
        self._show_standing()
        # A step shown while the runner was busy may want a different repo — serve it now.
        self._request_lists()

    # -- where the refs stand ---------------------------------------------------------------

    def _adopt_fresh_state(self) -> None:
        """What GitHub just said about the shown step's PR, written into the step the
        refresher's way — directly, with its origin, never onto the undo stack."""
        step = self.step()
        refs = read(step) if step is not None else None
        if step is None or refs is None or refs.pr_number is None:
            return
        info = self._prs.get(refs.pr_number)
        if info is None:
            return
        fresh = refreshed(refs, info)
        if fresh != refs:
            SetModuleDataCommand(
                step.id, MODULE_ID, write(fresh), view_origin=REFRESH_ORIGIN, label=""
            ).redo(self._library)

    def _refs(self) -> GithubRefs | None:
        step = self.step()
        return read(step) if step is not None else None

    def _pr_link(self) -> str:
        refs = self._refs()
        return pr_url(refs, self._repo()) if refs is not None else ""

    def _branch_link(self) -> str:
        refs = self._refs()
        return branch_url(refs, self._repo()) if refs is not None else ""

    @staticmethod
    def _open(url: str) -> None:
        if url:
            open_url(url)

    def standing_words(self) -> str:
        """Where the PR and the branch stand, from the last answer — the tab's status."""
        refs = self._refs()
        if refs is None:
            return ""
        lines = []
        if refs.has_pr():
            info = self._prs.get(refs.pr_number) if refs.pr_number is not None else None
            if info is not None:
                lines.append(
                    f"{pr_label(refs)} is {info.state}" + (f" · {info.title}" if info.title else "")
                )
            elif self._fetching:
                lines.append(f"{pr_label(refs)} — checking…")
            elif refs.pr_state:
                lines.append(f"{pr_label(refs)} was {refs.pr_state} when last seen")
            else:
                lines.append(f"{pr_label(refs)} — not checked yet")
        if refs.branch:
            if self._branches is not None:
                lines.append(
                    f"{refs.branch} is on the remote"
                    if refs.branch in self._branches
                    else f"{refs.branch} is not on the remote — deleted after the merge?"
                )
            elif self._fetching:
                lines.append(f"{refs.branch} — checking the remote…")
        return "\n".join(lines)

    def _show_standing(self) -> None:
        words = self.standing_words()
        self.standing.setText(words)
        self.standing.setVisible(bool(words))
        self.open_pr.setEnabled(bool(self._pr_link()))
        self.open_branch.setEnabled(bool(self._branch_link()))

    # -- reading and writing the step --------------------------------------------------------

    def load_step(self, step: Step | None) -> None:
        refs = read(step) if step is not None else None
        self.branch_edit.setEditText(refs.branch if refs else "")
        self.pr_edit.setEditText(self._pr_text(refs))
        self._show_standing()

    def _pr_text(self, refs: GithubRefs | None) -> str:
        if refs is None or not refs.has_pr():
            return ""
        return f"#{refs.pr_number}" if refs.pr_number is not None else refs.pr_url

    def entry(self, step: Step) -> dict[str, Any]:
        return write(self._refs_from_fields(read(step) or GithubRefs()))

    def _refs_from_fields(self, current: GithubRefs) -> GithubRefs:
        """What the two fields say, enriched from the fetched PR list when it matches.

        Free text that names a PR the list does not know keeps the stored state when the
        number is unchanged, and resets it to "never checked" otherwise — the refresher or
        ``dplanner github refresh`` fills it in.
        """
        branch = self.branch_edit.currentText().strip()
        pr_text = self.pr_edit.currentText().strip()
        number = pr_number_from(pr_text)
        if number is None:
            return GithubRefs(branch=branch)
        info = self._prs.get(number)
        if info is not None:
            return refreshed(GithubRefs(branch=branch), info)
        if number == current.pr_number:
            return replace(current, branch=branch)
        return GithubRefs(branch=branch, pr_number=number)
