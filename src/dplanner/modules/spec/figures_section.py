"""The Figures block on the step panel's Details tab: the spec figures beside this step.

`spec attach-to-step` and `step add --attach` copy rendered spec pages beside a step for
its briefing; this is the surface that shows them where the step is read. Read-only — the
figures are managed by the spec verbs and the Specs tab, and a detached figure's blob
deliberately stays on disk, so the gallery lists what the *attachments record* names, not
whatever the file area holds.
"""

from collections.abc import Callable

from PySide6.QtWidgets import QVBoxLayout, QWidget

from dplanner.domain.model import Library, NodeId
from dplanner.domain.store import ModuleFileArea
from dplanner.framework.asset_gallery import AssetGallery
from dplanner.modules.spec.aspect import read_attachments


class FiguresSection(QWidget):
    """An :class:`~dplanner.framework.inspector.InspectorExtension` over the attachments."""

    def __init__(self, library: Library, files: Callable[[NodeId], ModuleFileArea]) -> None:
        super().__init__()
        self._product = library
        self._files = files
        self._target_id: str | None = None

        self.gallery = AssetGallery(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # Margins belong to the Details tab.
        layout.addWidget(self.gallery)

        # Attachments arrive as module data (a CLI attach lands via reload, an in-window
        # one via the command), so the list follows the model like every aspect surface.
        self._unsubscribes = [
            library.module_data_changed.connect(self._on_module_data),
        ]

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._target_id = target_id
        self._reload()

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes = []

    # -- internals -----------------------------------------------------------------------------

    def _on_module_data(self, node_id: NodeId, _module_id: str, _origin: object) -> None:
        if node_id == self._target_id:
            self._reload()

    def _reload(self) -> None:
        target_id = self._target_id
        if target_id is None or not self._product.has(target_id):
            self.gallery.set_files([], None)
            return
        names = [entry.file for entry in read_attachments(self._product.step(target_id))]

        def read(name: str) -> bytes | None:
            # Resolved per read: a step flushed since the last look starts answering.
            try:
                return self._files(target_id).read_bytes(name)
            except KeyError:
                return None

        self.gallery.set_files(names, read)
