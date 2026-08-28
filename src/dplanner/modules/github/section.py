"""The GitHub tab: the branch and PR a step lands in, typed or picked.

Both fields are editable combos so recording works with no ``gh`` and no network — the
pickers are the enhancement, filled from GitHub in the background when the product has a
repository URL and ``gh`` can be used. Merged and closed PRs stay in the list, marked, so
a step can be pointed at work that already landed.
"""

import threading
from collections.abc import Callable
from dataclasses import replace
from functools import partial

from PySide6.QtCore import QObject, Qt
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Product, StepId
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

FORM_SPACING = 8
PANEL_MARGIN = 16

# Green for a merged check, red for a closed cross: the same low-alpha-tint family as the
# canvas (DESIGN.md exception #2), opaque here because it colours text, not a region.
MERGED_COLOUR = QColor(110, 180, 130)
CLOSED_COLOUR = QColor(200, 110, 110)

STATE_MARKS = {"merged": "✓ merged", "closed": "✗ closed"}


class _GhLoader(QObject):
    """One fetch of branches and PRs on a daemon thread; delivered on the GUI thread."""

    _finished = QtSignal(object, object, str)  # (branches, prs, refusal-or-error)

    def __init__(
        self,
        repo: str,
        on_done: Callable[[list[str], list[PrInfo], str], None],
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._on_done = on_done
        self._finished.connect(self._deliver)

    def start(self) -> None:
        def work() -> None:
            refusal = gh_refusal(check_auth=True)
            if refusal is not None:
                self._finished.emit([], [], refusal)
                return
            try:
                self._finished.emit(list_branches(self._repo), list_prs(self._repo), "")
            except GhError as error:
                self._finished.emit([], [], str(error))

        threading.Thread(target=work, daemon=True).start()

    def _deliver(self, branches: object, prs: object, message: str) -> None:
        self._on_done(
            branches if isinstance(branches, list) else [],
            prs if isinstance(prs, list) else [],
            message,
        )


class GithubSection(QWidget):
    def __init__(
        self,
        product: Product,
        undo: UndoService[Product],
        repository_for: Callable[[StepId], str],
    ) -> None:
        super().__init__()
        self._product = product
        self._undo = undo
        self._repository_for = repository_for
        self._step_id: StepId | None = None
        self._loading = False
        self._prs: dict[int, PrInfo] = {}
        # Which repo the pickers were (or are being) fetched for. Projects can carry their
        # own repository, so showing a step from another project may mean a refetch.
        self._loaded_repo: str | None = None

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
            line.editingFinished.connect(self._commit)
            combo.activated.connect(lambda _index: self._commit())
            self._lines.append(line)
        layout.addRow("Branch", self.branch_edit)
        layout.addRow("Pull request", self.pr_edit)

        self.status = QLabel(self)
        self.status.setObjectName("InspectorNote")
        self.status.setWordWrap(True)
        layout.addRow(self.status)

        self._unsubscribe = product.module_data_changed.connect(self._on_module_data)

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self.setEnabled(target_id is not None)
        self._load()
        self._request_lists()

    def dispose(self) -> None:
        self._unsubscribe()

    # -- the pickers -----------------------------------------------------------------------

    def _request_lists(self) -> None:
        """Start a background fetch for the shown step's repository, when it needs one.

        A step with no parseable GitHub repository never spawns a subprocess — which is
        also what keeps a test building the real panel deterministic.
        """
        if self._step_id is None or not self._product.has(self._step_id):
            return
        repo = parse_repo(self._repository_for(self._step_id))
        if repo is None:
            self.status.setText("Set a repository URL on the product to list branches and PRs")
            return
        if repo == self._loaded_repo:
            return
        self._loaded_repo = repo
        self.status.setText("Fetching branches and PRs…")
        self.status.show()
        deliver = partial(self._on_lists, repo)
        _GhLoader(repo, deliver, self).start()

    def _on_lists(self, repo: str, branches: list[str], prs: list[PrInfo], message: str) -> None:
        if repo != self._loaded_repo:
            return  # The shown step moved to another repo while this fetch was out.
        if message:
            self.status.setText(f"{message} — type values manually")
            return
        self.status.setText("")
        self.status.hide()
        self._prs = {pr.number: pr for pr in prs}
        # Repopulating must not commit a transient value.
        for combo in (self.branch_edit, self.pr_edit):
            combo.blockSignals(True)
        current_branch, current_pr = self.branch_edit.currentText(), self.pr_edit.currentText()
        self.branch_edit.clear()
        self.branch_edit.addItems(branches)
        self.pr_edit.clear()
        for index, pr in enumerate(prs):
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

    # -- reading and writing the step --------------------------------------------------------

    def _load(self) -> None:
        refs = None
        if self._step_id is not None and self._product.has(self._step_id):
            refs = read(self._product.step(self._step_id))
        self._loading = True
        try:
            self.branch_edit.setEditText(refs.branch if refs else "")
            self.pr_edit.setEditText(self._pr_text(refs))
        finally:
            self._loading = False

    def _pr_text(self, refs: GithubRefs | None) -> str:
        if refs is None or not refs.has_pr():
            return ""
        return f"#{refs.pr_number}" if refs.pr_number is not None else refs.pr_url

    def _commit(self) -> None:
        if self._loading or self._step_id is None or not self._product.has(self._step_id):
            return
        current = read(self._product.step(self._step_id)) or GithubRefs()
        refs = self._refs_from_fields(current)
        entry = write(refs)
        if entry == self._product.step(self._step_id).module_data.get(MODULE_ID, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._step_id, MODULE_ID, entry, view_origin=self, label="Set GitHub Refs"
            )
        )

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

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._step_id or module_id != MODULE_ID:
            return
        # The echo of our own write is ignored only while a field is being edited; an undo
        # made with the panel focused still has to reach the widgets.
        if origin is self and any(line.hasFocus() for line in self._lines):
            return
        self._load()
