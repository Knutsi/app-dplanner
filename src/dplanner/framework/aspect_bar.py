"""The aspect bar: templates on the left, every aspect toggle on the right.

The right half renders one child menu of the action table — Step ▸ Type — and never keeps
a list of its own: every glyph is a registered toggle, run through ``registry.run`` with
the context the host hands over, so each stays one undoable command and an aspect a build
does not ship has no button.

The left half is **templates**: named combinations of those toggles, handed over by the
composition root as data (a template is wired, never inferred). Clicking one runs whichever
toggles differ — on for the template's set, off for everything else — inside one undo
gesture, so *Make Milestone* is one Ctrl+Z however many aspects it moved. And it goes both
ways: a template reads as selected exactly when the step carries its set and nothing else,
so a combination somebody built by hand lights up the template it amounts to — and one
template may be the **catch-all**, lit whenever no other matches, because a step with an
unnamed combination of aspects is still a step. The bar never stores which template is
"current"; it is a comparison on every refresh.

Two ``QToolBar``s rather than one row of buttons, for the same reason the Tests tab has
two: a ``QToolBar`` too narrow for its contents grows the » overflow button and puts the
tail in a menu — as checkable entries, check marks and all — where a plain row would
simply clip. The left bar takes the slack, so at a width where anything has to go, the
toggles keep their glyphs and the templates fold first.

The context arrives as a function, not a ``ContextService``: the panel inside the details
dialog shows a step nobody selected and names it itself, and the bar cannot tell the
difference. The host calls :meth:`refresh` on every model change it hears, because a toggle
may have changed another toggle's state — and which template matches.
"""

from collections.abc import Callable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QHBoxLayout, QToolBar, QToolButton, QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService
from dplanner.theme.icons import ICON_SIZE, glyph_painter
from dplanner.theme.tones import button_tone

# DESIGN.md: a strip of verbs is chrome — 8 px inside its own frame, 12 between groups.
# Sixteen buttons share this row, so they sit 4 apart rather than the canvas strip's 6.
STRIP_MARGIN = 8
GROUP_GAP = 12
BUTTON_GAP = 4


@dataclass(frozen=True)
class AspectTemplate:
    """One template on the bar's left: a name, the toggles that are on, and its look."""

    label: str
    toggles: frozenset[str]  # Type toggle action ids that are on; every other one is off.
    tone: str | None = None  # A name in ``theme.tones.BODY_TONES``; None keeps the accent.
    glyph: str | None = None  # A name in ``theme.icons.GLYPH_ICONS``; None draws none.
    catch_all: bool = False  # Selected whenever no template matches exactly.
    catch_all: bool = False  # Selected whenever no template matches exactly.
    catch_all: bool = False  # Selected whenever no template matches exactly.


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


def _button(bar: QToolBar, action: QAction, *, worded: bool) -> QToolButton | None:
    bar.addAction(action)
    button = bar.widgetForAction(action)
    if not isinstance(button, QToolButton):
        return None
    button.setObjectName("ToolbarButton")
    # A toolbar never takes the keyboard from the editor it sits above.
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setToolButtonStyle(
        Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        if worded
        else Qt.ToolButtonStyle.ToolButtonIconOnly
    )
    return button


class AspectBar(QWidget):
    def __init__(
        self,
        registry: ActionRegistry,
        context: Callable[[], Context],
        templates: Sequence[AspectTemplate] = (),
        *,
        undo: UndoService[Any] | None = None,
        menu: str = "Step",
        submenu: str = "Type",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AspectBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._registry = registry
        self._context = context
        self._undo = undo
        self._specs: dict[str, ActionSpec] = {
            spec.id: spec
            for spec in registry.all_specs()
            if spec.menu == menu and spec.submenu == submenu
        }
        self._actions: dict[str, QAction] = {}
        self._templates: list[tuple[AspectTemplate, QAction]] = []

        self.templates_bar = _tool_bar(self)
        self.toggles_bar = _tool_bar(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN, STRIP_MARGIN)
        layout.setSpacing(GROUP_GAP)
        layout.addWidget(self.templates_bar, 1)
        layout.addWidget(self.toggles_bar)

        for template in templates:
            action = QAction(template.label, self.templates_bar)
            action.setCheckable(True)
            action.setToolTip(self._describe(template))
            action.triggered.connect(lambda _on=False, t=template: self._apply(t))
            _button(self.templates_bar, action, worded=True)
            self._templates.append((template, action))
        for action_id, spec in self._specs.items():
            action = QAction(spec.label.replace("&", ""), self.toggles_bar)
            action.setCheckable(True)
            action.triggered.connect(lambda _on=False, a=action_id: self._run(a))
            _button(self.toggles_bar, action, worded=False)
            self._actions[action_id] = action
        self.refresh()

    # -- what a template is made of ------------------------------------------------------------

    def _describe(self, template: AspectTemplate) -> str:
        names = [
            spec.label.replace("&", "")
            for action_id, spec in self._specs.items()
            if action_id in template.toggles
        ]
        return f"{template.label}: {', '.join(names)}" if names else template.label

    def _states(self) -> dict[str, tuple[bool, bool, bool]]:
        """Per toggle: (visible, enabled, checked) right now."""
        now = self._context()
        return {
            action_id: (state.visible, state.enabled, bool(state.checked))
            for action_id, spec in self._specs.items()
            for state in (spec.state(now),)
        }

    # -- running ----------------------------------------------------------------------------

    def _run(self, action_id: str) -> None:
        self._registry.run(action_id, self._context())
        # The action's own checked flip is a guess; the model is the answer, and a toggle
        # may have changed another toggle's state too.
        self.refresh()

    def _apply(self, template: AspectTemplate) -> None:
        """Run every toggle that differs from the template, as one undo step."""
        changes = [
            action_id
            for action_id, (visible, enabled, checked) in self._states().items()
            if visible and enabled and checked != (action_id in template.toggles)
        ]
        grouping = (
            self._undo.gesture(f"Make {template.label}")
            if self._undo is not None
            else nullcontext()
        )
        with grouping:
            for action_id in changes:
                self._registry.run(action_id, self._context())
        self.refresh()

    def refresh(self) -> None:
        """Re-read every toggle's state, and which template the step now amounts to."""
        states = self._states()
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
        offered = {action_id for action_id, (visible, _e, _c) in states.items() if visible}
        checked = {action_id for action_id, (_v, _e, is_on) in states.items() if is_on}
        any_enabled = any(enabled for _v, enabled, _c in states.values())
        # Exactly its set, and nothing else the build offers: a combination is a template.
        matched = {
            template.label
            for template, _action in self._templates
            if checked == (template.toggles & offered)
        }
        for template, action in self._templates:
            action.setEnabled(any_enabled)
            selected = template.label in matched or (template.catch_all and not matched)
            action.setChecked(any_enabled and selected)

    def paint(self, ink: str | QColor) -> None:
        """Glyphs in the theme's secondary text colour; re-call on theme change."""
        colour = QColor(ink)
        for action_id, action in self._actions.items():
            spec = self._specs[action_id]
            if spec.icon is not None:
                action.setIcon(spec.icon(colour))
        for template, action in self._templates:
            painter = glyph_painter(template.glyph) if template.glyph else None
            if painter is not None:
                action.setIcon(painter(colour))
            tone = button_tone(template.tone) if template.tone else None
            button = self.templates_bar.widgetForAction(action)
            if tone is not None and button is not None:
                fill, border = tone
                button.setStyleSheet(
                    "QToolButton:checked {"
                    f" background-color: {fill.name(QColor.NameFormat.HexArgb)};"
                    f" border-color: {border.name(QColor.NameFormat.HexArgb)};"
                    " color: palette(text); }"
                )

    # -- a test's way in ---------------------------------------------------------------------

    def action(self, action_id: str) -> QAction:
        """The bar's action for one toggle id."""
        return self._actions[action_id]

    def template(self, label: str) -> QAction:
        """The bar's action for one template, by its label."""
        return next(action for template, action in self._templates if template.label == label)

    def toggle_ids(self) -> list[str]:
        """The toggle ids the right bar carries, in registry order."""
        return list(self._actions)

    def template_labels(self) -> list[str]:
        return [template.label for template, _action in self._templates]
