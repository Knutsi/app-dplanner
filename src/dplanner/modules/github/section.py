"""The GitHub tab: the branch and PR a step lands in, typed or picked.

Both fields are editable combos so recording works with no ``gh`` and no network — the
pickers are the enhancement, filled from GitHub in the background when the library has a
repository URL and ``gh`` can be used. Merged and closed PRs stay in the list, marked, so
a step can be pointed at work that already landed.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit

from dplanner.domain.model import Library, Step, StepId
from dplanner.framework.module_data_section import (
    FORM_SPACING,
    PANEL_MARGIN,
    ModuleDataSection,
)
from dplanner.framework.task_runner import TaskRunner
from dplanner.framework.tasks import TaskService
from dplanner.framework.undo import UndoService
from dplanner.modules.github.aspect import MODULE_ID, GithubRefs, read, refreshed, write
from dplanner.modules.github.gh import (
    GhError,
    PrInfo,
    gh_refusal,
    list_branches,
    list_prs,
    parse_repo,
    pr_number_from,
)

# Green for a merged check, red for a closed cross: the same low-alpha-tint family as the
# canvas (DESIGN.md exception #2), opaque here because it colours text, not a region.
MERGED_COLOUR = QColor(110, 180, 130)
CLOSED_COLOUR = QColor(200, 110, 110)

STATE_MARKS = {"merged": "✓ merged", "closed": "✗ closed"}


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
        # Which repo the pickers were (or are being) fetched for. Projects can carry their
        # own repository, so showing a step from another project may mean a refetch.
        self._loaded_repo: str | None = None
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

        self.status = QLabel(self)
        self.status.setObjectName("InspectorNote")
        self.status.setWordWrap(True)
        layout.addRow(self.status)

    def show_target(self, target_id: str | None) -> None:
        super().show_target(target_id)
        self._request_lists()

    # -- the pickers -----------------------------------------------------------------------

    def _request_lists(self) -> None:
        """Start a background fetch for the shown step's repository, when it needs one.

        A step with no parseable GitHub repository never spawns a subprocess — which is
        also what keeps a test building the real panel deterministic.
        """
        step = self.step()
        if step is None:
            return
        repo = parse_repo(self._repository_for(step.id))
        if repo is None:
            self.status.setText(
                "Set the project's code repository (Project ▸ Settings…) to list branches and PRs"
            )
            return
        if repo == self._loaded_repo:
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
            self._loaded_repo = repo
            self.status.setText("Fetching branches and PRs…")
            self.status.show()

    def _on_lists(self, repo: str, branches: object, prs: object, message: str) -> None:
        branch_names = branches if isinstance(branches, list) else []
        pr_infos = prs if isinstance(prs, list) else []
        if repo != self._loaded_repo:
            return  # The shown step moved to another repo while this fetch was out.
        if message:
            self.status.setText(f"{message} — type values manually")
            return
        self.status.setText("")
        self.status.hide()
        self._prs = {pr.number: pr for pr in pr_infos}
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
        # A step shown while the runner was busy may want a different repo — serve it now.
        self._request_lists()

    # -- reading and writing the step --------------------------------------------------------

    def load_step(self, step: Step | None) -> None:
        refs = read(step) if step is not None else None
        self.branch_edit.setEditText(refs.branch if refs else "")
        self.pr_edit.setEditText(self._pr_text(refs))

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
