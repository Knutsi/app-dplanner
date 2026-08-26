"""An in-tab action toolbar: one button per action id, restated on every context change.

The registry stays the single source of truth — this presenter renders a chosen subset of
specs as buttons, exactly as the menu bar renders all of them as QActions. Shortcuts stay
with the menu bar's QActions; a click here goes through ``registry.run``, so the state
gate holds even if a stale context left a button enabled. Toolbars live inside tabs, so
unlike the app-lifetime menu bar they must be ``dispose()``d when their tab closes.

**It renders the application's action state, not its own tab's.** A toolbar in a background
tab — or in a tab group the user is not in — shows what the *active* surface can do, because
there is one ``ContextService``. Invisible while only one tab is on screen; visible once the
window is split. If that ever matters, the fix is a ``set_active(bool)`` that greys the row
when its group is not the active one, not a context per group.
"""

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QToolButton, QWidget

from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import Context, ContextService


class ActionToolbar(QWidget):
    def __init__(
        self,
        registry: ActionRegistry,
        context: ContextService,
        action_ids: Sequence[str],
        button_text: Mapping[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ActionToolbar")
        self._registry = registry
        self._context = context
        # Per-action face override (glyphs, short forms); the spec label becomes the
        # tooltip fallback so no meaning is lost on a compact button.
        self._button_text = dict(button_text or {})
        self._buttons: dict[str, QToolButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for action_id in action_ids:
            button = QToolButton(self)
            button.setObjectName("ToolbarButton")
            # A toolbar never takes the keyboard. Without this, clicking a button moves focus
            # off the surface the button just acted on, and the next keystroke goes nowhere —
            # which a canvas with its own key bindings notices immediately.
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # And it keeps its face: a layout short of room shrinks widgets to their minimum,
            # and a 10 px wide button with a 16 px glyph in it shows neither icon nor label.
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                lambda _checked=False, a=action_id: registry.run(a, context.current())
            )
            layout.addWidget(button)
            self._buttons[action_id] = button

        self._unsubscribe = context.changed.connect(self._refresh)
        self._refresh(context.current())

    def set_button_icons(self, icons: Mapping[str, QIcon]) -> None:
        """Painted icons per action id; with an empty text override the button renders
        icon-only (the spec label survives as the tooltip). Re-call on theme changes."""
        for action_id, icon in icons.items():
            button = self._buttons.get(action_id)
            if button is not None:
                button.setIcon(icon)

    def _refresh(self, context: Context) -> None:
        for action_id, button in self._buttons.items():
            spec = self._registry.spec(action_id)
            state = spec.state(context)
            label = state.label if state.label is not None else spec.label
            text = self._button_text.get(action_id, label.replace("&", ""))
            button.setText(text)
            # QToolButton shows its icon and nothing else unless told otherwise, so a button
            # with words on it has to say so — and one with an empty override stays a glyph.
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                if text
                else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            button.setVisible(state.visible)
            button.setEnabled(state.enabled)
            if state.checked is not None:
                button.setCheckable(True)
                button.setChecked(state.checked)
            button.setToolTip(spec.tip or label.replace("&", ""))

    def dispose(self) -> None:
        self._unsubscribe()
