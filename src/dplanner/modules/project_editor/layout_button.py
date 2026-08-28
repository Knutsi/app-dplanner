"""The layout picker: one button on the canvas toolbar, wearing the applied layout's name.

Saved layout names are data, so the popup is built fresh every time it opens rather than
from the action registry — but everything in it with a fixed identity (the sorts, save,
update, rename, delete) renders *through* the registry, honouring the same state gates as
the menu bar, so the popup can never say something the menu would not.

The face carries a modified dot: “• release plan” means the graph has drifted since that
layout was applied — a drag, a new step, an edit from the CLI. The comparison is one dict
build over the project's steps, cheap at the scale a project has.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from dplanner.domain.model import NodeId, Product, Project
from dplanner.framework.action_menu import append_action
from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.modules.project_editor.layout_verbs import (
    MANAGE_ACTION_IDS,
    SORT_ACTION_IDS,
    LayoutVerbs,
    current_layout_name,
)
from dplanner.modules.project_editor.named_layouts import is_current, read_layouts
from dplanner.modules.project_editor.positions import MODULE_ID


class LayoutButton(QToolButton):
    """The named-layout dropdown at the right end of the canvas toolbar."""

    def __init__(
        self,
        product: Product,
        project_id: NodeId,
        actions: ActionRegistry,
        context: ContextService,
        verbs: LayoutVerbs,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._product = product
        self._project_id = project_id
        self._actions = actions
        self._context = context
        self._verbs = verbs

        self.setObjectName("LayoutButton")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # Like every toolbar button: a click must not take the keyboard off the canvas.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Saved layouts of this graph, and the sorts that arrange it")
        self._menu = QMenu(self)
        self._menu.aboutToShow.connect(self._rebuild_menu)
        self.setMenu(self._menu)

        self._unsubscribes: list[Callable[[], None]] = [
            product.module_data_changed.connect(self._on_module_data),
            product.structure_changed.connect(lambda *_args: self._refresh_face()),
        ]
        self._refresh_face()

    def build_popup(self) -> QMenu:
        """The popup as it would open right now — how a test asks what it offers."""
        self._rebuild_menu()
        return self._menu

    def dispose(self) -> None:
        for unsubscribe in self._unsubscribes:
            unsubscribe()
        self._unsubscribes.clear()

    # -- the face --------------------------------------------------------------------------------

    def _project(self) -> Project | None:
        if not self._product.has(self._project_id):
            return None
        return self._product.project(self._project_id)

    def _applied_name(self) -> str | None:
        project = self._project()
        if project is None:
            return None
        name = current_layout_name(self._project_id)
        if name is None or name not in read_layouts(project):
            return None
        return name

    def _on_module_data(self, _node_id: NodeId, module_id: str, _origin: object) -> None:
        if module_id == MODULE_ID:
            self._refresh_face()

    def _refresh_face(self) -> None:
        project = self._project()
        name = self._applied_name()
        if project is None or name is None:
            self.setText("Layout")
            return
        modified = not is_current(self._product, project, name)
        self.setText(f"• {name}" if modified else name)

    # -- the popup -------------------------------------------------------------------------------

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        project = self._project()
        if project is None:
            return
        applied = self._applied_name()
        names = sorted(read_layouts(project))
        for name in names:
            entry = self._menu.addAction(name)
            entry.setCheckable(True)
            entry.setChecked(name == applied)
            entry.triggered.connect(
                lambda _checked=False, n=name: self._verbs.apply(self._project_id, n)
            )
        if names and SORT_ACTION_IDS:
            self._menu.addSeparator()
        for action_id in SORT_ACTION_IDS:
            append_action(self._menu, self._actions, self._context, action_id)
        if names or SORT_ACTION_IDS:
            self._menu.addSeparator()
        for action_id in MANAGE_ACTION_IDS:
            append_action(self._menu, self._actions, self._context, action_id)
