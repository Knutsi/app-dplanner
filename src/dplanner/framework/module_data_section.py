"""A detail-panel section over one module's ``module_data`` entry.

The structured twin of :mod:`dplanner.framework.prose_section`, and written once for the
same reason: the binding mechanics are the easy-to-get-wrong half, and getting them wrong
is quiet. Four aspect editors had hand-rolled this scaffold and one had drifted — its echo
guard swallowed an undo made while its field was focused.

What the base owns: the ``module_data_changed`` subscription and its teardown, reloading on
every target change, the no-op-when-unchanged commit through the undo stack, and the echo
rule — **a section ignores the echo of its own write only while one of its fields is being
edited**, because an undo made with the panel focused still has to reach the widgets.

A subclass builds its widgets in ``__init__``, implements :meth:`load_step` (fill the
widgets from a step, or clear them for ``None``) and :meth:`entry` (the dict its widgets
say the step's entry should be), and calls :meth:`commit` from its edit-finished handlers.
``load_step`` runs with commits suppressed, so filling a widget cannot write back.
"""

from typing import Any

from PySide6.QtWidgets import QApplication, QWidget

from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, NodeId, Step, StepId
from dplanner.framework.undo import UndoService

# DESIGN.md: side panels get 16 px outer margins and 6 px from a field to what belongs
# with it. Here so every section spells the numbers the same way.
PANEL_MARGIN = 16
FIELD_GAP = 6
FORM_SPACING = 8


class ModuleDataSection(QWidget):
    """One module's structured entry on one step, edited through the undo stack."""

    def __init__(
        self,
        library: Library,
        undo: UndoService[Library],
        *,
        module_id: str,
        undo_label: str,
    ) -> None:
        super().__init__()
        self._library = library
        self._undo = undo
        self._module_id = module_id
        self._undo_label = undo_label
        self._step_id: StepId | None = None
        self._loading = False
        self._unsubscribe = library.module_data_changed.connect(self._on_module_data)

    # -- the InspectorExtension contract -------------------------------------------------------

    @property
    def widget(self) -> QWidget:
        return self

    def show_target(self, target_id: str | None) -> None:
        self._step_id = target_id
        self.setEnabled(target_id is not None)
        self.reload()

    def dispose(self) -> None:
        self._unsubscribe()

    # -- what the subclass calls and reads -----------------------------------------------------

    def step(self) -> Step | None:
        """The shown step — None while nothing is shown or the step is gone."""
        if self._step_id is not None and self._library.has(self._step_id):
            return self._library.step(self._step_id)
        return None

    def reload(self) -> None:
        self._loading = True
        try:
            self.load_step(self.step())
        finally:
            self._loading = False

    def commit(self) -> None:
        """Push the widgets' state as one command — a no-op when nothing changed."""
        if self._loading:
            return
        step = self.step()
        if step is None:
            return
        entry = self.entry(step)
        if entry == step.module_data.get(self._module_id, {}):
            return
        self._undo.push(
            SetModuleDataCommand(
                step.id, self._module_id, entry, view_origin=self, label=self._undo_label
            )
        )

    # -- what the subclass implements ----------------------------------------------------------

    def load_step(self, step: Step | None) -> None:
        """Fill the widgets from ``step``; clear them when it is None."""
        raise NotImplementedError

    def entry(self, step: Step) -> dict[str, Any]:
        """The entry the widgets describe. ``{}`` removes the file — see FORMAT.md."""
        raise NotImplementedError

    def editing(self) -> bool:
        """Whether one of this section's fields is being edited right now.

        The default — focus is inside this widget — fits a section whose fields are its
        children; override when editing lives somewhere subtler.
        """
        focus = QApplication.focusWidget()
        return focus is not None and self.isAncestorOf(focus)

    # -- internals -----------------------------------------------------------------------------

    def _on_module_data(self, node_id: NodeId, module_id: str, origin: object) -> None:
        if node_id != self._step_id or module_id != self._module_id:
            return
        if origin is self and self.editing():
            return
        self.reload()
