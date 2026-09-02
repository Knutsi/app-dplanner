"""The aspect bar: what a step *is* on the left, what it *carries* on the right.

It renders one child menu of the action table — Step ▸ Type — and never keeps a list of
its own: every button is a registered toggle, run through ``registry.run`` with the context
the host hands over, so each stays one undoable command and an aspect a build does not ship
has no button. The kinds are named by the composition root (a kind is wired, never
inferred): those go left, worded and wearing their body tone when checked; everything else
in the submenu goes right as a glyph.

Two ``QToolBar``s rather than one row of buttons, for the same reason the Tests tab has
two: a ``QToolBar`` too narrow for its contents grows the » overflow button and puts the
tail in a menu — as checkable entries, check marks and all — where a plain row would
simply clip. The left bar takes the slack, so at a width where anything has to go, the
facets keep their glyphs and the kinds fold first.

The context arrives as a function, not a ``ContextService``: the panel inside the details
dialog shows a step nobody selected and names it itself, and the bar cannot tell the
difference. The host calls :meth:`refresh` on every model change it hears, because a toggle
may have changed another toggle's state.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QHBoxLayout, QToolBar, QToolButton, QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.theme.icons import ICON_SIZE
from dplanner.theme.tones import button_tone

# DESIGN.md: a strip of verbs is chrome — 8 px inside its own frame, 12 between groups.
STRIP_MARGIN = 8
GROUP_GAP = 12
BUTTON_GAP = 6


@dataclass(frozen=True)
class KindButton:
    """One kind on the bar's left: the toggle's action id and the tone it wears checked."""

    action_id: str
    tone: str | None = None  # A name in ``theme.tones.BODY_TONES``; None keeps the accent.


def _tool_bar(parent: QWidget) -> QToolBar:
    bar = QToolBar(parent)
    bar.setObjectName("AspectBarTools")
    bar.setMovable(False)
    bar.setFloatable(False)
    bar.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    inner = bar.layout()
    if inner is not None:
        inner.setSpacing(BUTTON_GAP)
        inner.setContentsMargins(0, 0, 0, 0)
    return bar


class AspectBar(QWidget):
    def __init__(
        self,
        registry: ActionRegistry,
        context: Callable[[], Context],
        kinds: Sequence[KindButton] = (),
        *,
        menu: str = "Step",
        submenu: str = "Type",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AspectBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._registry = registry
        self._context = context
        self._specs: dict[str, ActionSpec] = {
            spec.id: spec
            for spec in registry.all_specs()
            if spec.menu == menu and spec.submenu == submenu
        }
        self._actions: dict[str, QAction] = {}
        self._tones: dict[str, str] = {}

        self.kinds_bar = _tool_bar(self)
        self.facets_bar = _tool_bar(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN)
        layout.setSpacing(GROUP_GAP)
        layout.addWidget(self.kinds_bar, 1)
        layout.addWidget(self.facets_bar)

        kind_ids = [kind.action_id for kind in kinds if kind.action_id in self._specs]
        for kind in kinds:
            if kind.action_id in self._specs:
                self._add(self.kinds_bar, kind.action_id, worded=True)
                if kind.tone is not None:
                    self._tones[kind.action_id] = kind.tone
        for action_id in self._specs:
            if action_id not in kind_ids:
                self._add(self.facets_bar, action_id, worded=False)
        self.refresh()

    def _add(self, bar: QToolBar, action_id: str, *, worded: bool) -> None:
        spec = self._specs[action_id]
        action = QAction(spec.label.replace("&", ""), bar)
        action.setCheckable(True)
        action.triggered.connect(lambda _on=False, a=action_id: self._run(a))
        bar.addAction(action)
        button = bar.widgetForAction(action)
        if isinstance(button, QToolButton):
            button.setObjectName("ToolbarButton")
            # A toolbar never takes the keyboard from the editor it sits above.
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                if worded
                else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
        self._actions[action_id] = action

    def _run(self, action_id: str) -> None:
        self._registry.run(action_id, self._context())
        # The action's own checked flip is a guess; the model is the answer, and a toggle
        # may have changed another toggle's state too.
        self.refresh()

    def refresh(self) -> None:
        """Re-read every toggle's state — visible, enabled, checked, and what it says."""
        now = self._context()
        for action_id, action in self._actions.items():
            spec = self._specs[action_id]
            state = spec.state(now)
            label = (state.label if state.label is not None else spec.label).replace("&", "")
            action.setVisible(state.visible)  # Hidden means this build lacks the capability.
            action.setEnabled(state.enabled)
            action.setChecked(bool(state.checked))
            action.setText(label)
            action.setToolTip(spec.tip or label)

    def paint(self, ink: str | QColor) -> None:
        """Glyphs in the theme's secondary text colour; re-call on theme change."""
        colour = QColor(ink)
        for action_id, action in self._actions.items():
            spec = self._specs[action_id]
            if spec.icon is not None:
                action.setIcon(spec.icon(colour))
            tone = button_tone(self._tones[action_id]) if action_id in self._tones else None
            button = self.kinds_bar.widgetForAction(action)
            if tone is not None and button is not None:
                fill, border = tone
                button.setStyleSheet(
                    "QToolButton:checked {"
                    f" background-color: {fill.name(QColor.NameFormat.HexArgb)};"
                    f" border-color: {border.name(QColor.NameFormat.HexArgb)};"
                    " color: palette(text); }"
                )

    def action(self, action_id: str) -> QAction:
        """The bar's action for one toggle id — a test's way in."""
        return self._actions[action_id]

    def ids(self, bar: QToolBar) -> list[str]:
        """The toggle ids one of the two bars carries, in order."""
        return [action_id for action_id, action in self._actions.items() if action in bar.actions()]
