"""The repository/checkout fields the project panel hosts, with an advisory status line.

The status is a note, never an alarm: whether the checkout exists and is a git
repository, and whether the GitHub CLI is around. The probes arrive as callables wired by
the composition root — this module may not name a concrete storage provider. The instant
ones (a filesystem walk, a ``which``) run on every load; the signed-in probe does a
network round trip with no timeout, so it runs **once per process**, on a daemon thread,
its answer cached at module level and delivered back through a queued Qt signal — the
panel never blocks and never re-probes. Nothing is gated on any of it; a plain folder is
a legitimate checkout.

The future ``github`` module will make its own gh checks — deliberately: a shared probe
would be coupling, and the check is two lines.
"""

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import NodeId, Product
from dplanner.framework.undo import UndoService
from dplanner.modules.project_repo.repo import (
    MODULE_ID,
    read_checkout,
    read_repository,
    write_association,
)

FIELD_GAP = 8  # Between form rows, matching the panel's Name/Summary form.
NOTE_GAP = 6  # DESIGN.md: a remark sits 6 under what it belongs to.

# One answer per process: None while unknown, then whatever `gh auth status` said.
_gh_auth_cache: bool | None = None


class _GhProbe(QObject):
    """Runs the auth check once on a daemon thread; the result lands on the GUI thread
    (queued — connected to a bound method of this GUI-owned object)."""

    _finished = Signal(bool)

    def __init__(
        self, probe: Callable[[], bool], on_done: Callable[[], None], parent: QObject
    ) -> None:
        super().__init__(parent)
        self._probe = probe
        self._on_done = on_done
        self._finished.connect(self._deliver)

    def start(self) -> None:
        def work() -> None:
            try:
                self._finished.emit(self._probe())
            except Exception:  # A probe must never take the panel down with it.
                self._finished.emit(False)

        threading.Thread(target=work, daemon=True).start()

    def _deliver(self, authenticated: bool) -> None:
        global _gh_auth_cache
        _gh_auth_cache = authenticated
        self._on_done()


class RepoFieldsWidget(QWidget):
    """Repository and checkout for one project, re-targeted as the panel's context moves."""

    def __init__(
        self,
        product: Product,
        undo: UndoService[Product],
        parent: QWidget | None = None,
        *,
        # The probes, wired by the composition root from the storage layer — this module
        # may not name a concrete provider. An unwired probe's fact is simply not said.
        is_git_repo: Callable[[Path], bool] | None = None,
        gh_installed: Callable[[], bool] | None = None,
        gh_signed_in: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._product = product
        self._undo = undo
        self._is_git_repo = is_git_repo
        self._gh_installed = gh_installed
        self._gh_signed_in = gh_signed_in
        self._project_id: NodeId | None = None
        self._loading = False
        self._probe: _GhProbe | None = None

        self.repository = QLineEdit(self)
        self.repository.setPlaceholderText("https://github.com/owner/repo")
        self.repository.editingFinished.connect(self._commit)

        self.checkout = QLineEdit(self)
        self.checkout.editingFinished.connect(self._commit)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._browse)
        checkout_row = QHBoxLayout()
        checkout_row.setSpacing(FIELD_GAP)
        checkout_row.addWidget(self.checkout, 1)
        checkout_row.addWidget(browse)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(FIELD_GAP)
        form.addRow("Repository", self.repository)
        form.addRow("Checkout", checkout_row)

        self.status = QLabel("", self)
        self.status.setObjectName("InspectorNote")
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(NOTE_GAP)  # The status note hangs 6 under the form it remarks on.
        layout.addLayout(form)
        layout.addWidget(self.status)

        self._unsubscribes = [
            product.module_data_changed.connect(self._on_module_data),
            product.field_changed.connect(self._on_product_field),
        ]

    # -- the host's side of the contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def set_project(self, project_id: NodeId | None) -> None:
        self._project_id = project_id if project_id and self._product.has(project_id) else None
        self.setEnabled(self._project_id is not None)
        self._load()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()

    # -- editing -------------------------------------------------------------------------------

    def _commit(self) -> None:
        # editingFinished also fires during teardown, when the project may be gone.
        if self._loading or self._project_id is None or not self._product.has(self._project_id):
            return
        entry = write_association(self.repository.text(), self.checkout.text())
        project = self._product.project(self._project_id)
        if entry == project.module_data.get(MODULE_ID, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                self._project_id,
                MODULE_ID,
                entry,
                view_origin=self,
                label="Set Project Repository",
            )
        )
        self._refresh_status()

    def _browse(self) -> None:
        if self._project_id is None:
            return
        start = self._effective_checkout() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose the Checkout", start)
        if not chosen:
            return
        self.checkout.setText(chosen)
        self._commit()

    # -- reading -------------------------------------------------------------------------------

    def _load(self) -> None:
        repository = checkout = ""
        if self._project_id is not None:
            project = self._product.project(self._project_id)
            repository = read_repository(project)
            checkout = read_checkout(project)
        self._loading = True
        try:
            if not self.repository.hasFocus():
                self.repository.setText(repository)
            if not self.checkout.hasFocus():
                self.checkout.setText(checkout)
        finally:
            self._loading = False
        # The fallback stays visible without being written: absence is the product's.
        fallback = self._product.checkout
        self.checkout.setPlaceholderText(
            f"Using the product's checkout: {fallback}"
            if fallback
            else "Where this project's code is cloned"
        )
        self._refresh_status()

    def _effective_checkout(self) -> str:
        checkout = self.checkout.text().strip()
        return checkout or self._product.checkout

    def _refresh_status(self) -> None:
        self.status.setText(" ".join(self._checkout_facts() + self._gh_facts()))
        self.status.setVisible(bool(self.status.text()))

    def _checkout_facts(self) -> list[str]:
        effective = self._effective_checkout()
        if not effective:
            return []
        path = Path(effective).expanduser()
        if not path.is_dir():
            return ["The checkout folder does not exist on this machine."]
        if self._is_git_repo is None:
            return []
        if not self._is_git_repo(path):
            return ["The checkout is not a git repository."]
        return ["The checkout is a git repository."]

    def _gh_facts(self) -> list[str]:
        if self._gh_installed is None:
            return []
        if not self._gh_installed():
            return ["The GitHub CLI (gh) is not installed."]
        if self._gh_signed_in is None:
            return ["gh is installed."]
        if _gh_auth_cache is None:
            self._start_probe()
            return ["gh is installed."]
        return ["gh is signed in." if _gh_auth_cache else "gh is installed but not signed in."]

    def _start_probe(self) -> None:
        if self._probe is None and self._gh_signed_in is not None:
            self._probe = _GhProbe(self._gh_signed_in, self._refresh_status, self)
            self._probe.start()

    # -- staying current -----------------------------------------------------------------------

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._project_id or module_id != MODULE_ID:
            return
        # The echo of our own write is ignored only while a field is being edited; an undo
        # made with the panel focused still has to reach the widgets.
        if origin is self and (self.repository.hasFocus() or self.checkout.hasFocus()):
            return
        self._load()

    def _on_product_field(self, node_id: NodeId, field: str, _origin: object) -> None:
        # The fallback shown in the placeholder must follow the identity tab.
        if node_id == self._product.id and field == "checkout":
            self._load()
