"""The strip of verbs over the canvas: glyphs in named bands, the way a drawing tool's is.

It renders **action ids and nothing else**. The step verbs next door, the app shell's undo
pair and the order module's ``order.open`` all arrive the same way, and this module imports
none of them — the registry is the only thing between them, so adding a button is adding a
string to :data:`GROUPS`, and the glyph comes with the spec.

**The band is the structure a toolbar has**, so it is spelled out here rather than inferred
from the menus, where these verbs sit under four different headings. It is named, because
nineteen glyphs in a row are nineteen riddles and six named bands of three or four are a
tool palette; and it is the unit the strip folds by, so a band is either on the strip or
whole in the ``…`` menu. ``framework/toolbar.py``'s ``Toolbar`` owns all of that.

The last band is a **face**, not a verb: one glyph dropping the Graph menu's ``look`` band
— framing, the marks, the spotlight, the grid and the ground. Those were six worded
switches on the strip once, which is what a row of words costs; how the graph is *drawn* is
a question asked rarely and answered in a menu, where each choice can say what it means.
The panel toggle sits beside it for the same reason: it is about this tab, not about the
plan.

The layout picker is outside the strip and never folds — it names the arrangement the
canvas is showing, which is a fact rather than a verb.
"""

from collections.abc import Sequence

from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import ContextService
from dplanner.framework.toolbar import Toolbar
from dplanner.theme.icons import options_icon
from dplanner.theme.tokens import CONTROL_GAP, FIELD_GAP

GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Where you are looking leads: a graph is a place before it is a thing to edit.
    ("Go", ("steps.jump", "canvas.frame", "order.open")),
    ("Step", ("steps.new", "steps.rename", "steps.delete", "steps.lasso")),
    ("Link", ("steps.connect", "steps.redirect_to", "steps.unlink", "steps.isolate")),
    ("Arrange", ("canvas.sort_flow", "canvas.divide_vertical")),
    ("History", ("appshell.undo", "appshell.redo")),
)

# Which child menu a button drops down. The button half still runs its own verb — Sort
# lays the graph out the layered way, Divide cuts upright, Redirect moves the arrowheads —
# and the arrow offers the rest of the family, rendered from the action table rather than
# copied, so a sort added to the menus appears here having touched nothing.
MENUS: dict[str, tuple[str, str]] = {
    "canvas.sort_flow": ("Graph", "Sort"),
    "canvas.divide_vertical": ("Graph", "Divide"),
    "steps.redirect_to": ("Step", "Redirect"),
}

# The last band: how the graph is drawn, and what stands beside it. Both are about this
# tab rather than about the plan, which is what puts them together and at the end.
OPTIONS = "Options"
LOOK_FACE = "Look"
LOOK_MENU = ("Graph", "look")
PANEL_ACTION = "canvas.side_panel"


class CanvasToolbar(QWidget):
    """One row of bands over the canvas, with the tab's own controls at its end."""

    def __init__(
        self,
        actions: ActionRegistry,
        context: ContextService,
        parent: QWidget | None = None,
        groups: Sequence[tuple[str, Sequence[str]]] = GROUPS,
        trailing: Sequence[QWidget] = (),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasToolbar")

        row = QHBoxLayout(self)
        row.setContentsMargins(FIELD_GAP, FIELD_GAP, FIELD_GAP, FIELD_GAP)
        row.setSpacing(CONTROL_GAP)
        # Dense: the glyphs of a band are read as one set, so they pack — the bands
        # themselves keep the strip's own gap and a hairline between them.
        self.tools = Toolbar(self, dense=True)
        for label, action_ids in groups:
            self.tools.add_group(label)
            for action_id in action_ids:
                self.tools.add_action(actions, context, action_id, menu=MENUS.get(action_id))
        self.tools.add_group(OPTIONS)
        self.look = self.tools.add_menu_face(
            LOOK_FACE, options_icon, actions, context, LOOK_MENU[0], group=LOOK_MENU[1]
        )
        self.tools.add_action(actions, context, PANEL_ACTION)
        row.addWidget(self.tools, 1)
        for widget in trailing:
            # The far end of the strip — the layout picker's seat, owned by whoever made
            # it. Outside the toolbar, so it is the one thing that never overflows: it
            # names the arrangement the canvas is showing, which is not a verb.
            row.addWidget(widget)

    def button(self, action_id: str) -> QToolButton | None:
        """The button for one action id — how a test asks what the row is saying."""
        return self.tools.button_for(action_id)

    def menu_for(self, action_id: str) -> QMenu | None:
        """The child menu a button's arrow drops, filled as it would open."""
        return self.tools.menu_for(action_id)

    def look_menu(self) -> QMenu:
        """What the Options face drops, filled as it would open."""
        return self.tools.face_menu(self.look)

    def dispose(self) -> None:
        """Toolbars live inside a tab and must let go of the context when it closes."""
        self.tools.dispose()
