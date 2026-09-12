"""The aspect bar: every aspect toggle on the left, the template it amounts to on the right.

The left renders one child menu of the action table — Step ▸ Type — and never keeps a list
of its own: every glyph is a registered toggle, run through ``registry.run`` with the
context the host hands over, so each stays one undoable command and an aspect a build does
not ship has no button. It is a :class:`~dplanner.framework.toolbar.Toolbar`, so what no
longer fits folds into that strip's ``…`` menu as glyph *and* words. Dense, because these
glyphs are read as one set — the row answers *what does this step carry* — rather than
aimed at one at a time, and a set that folds stops answering.

The right is **templates**: named combinations of those toggles, handed over by the
composition root as data (a template is wired, never inferred). They are one dropdown
rather than a row of buttons, wearing the name and glyph of the template the step amounts
to right now, because only one of them is ever true at a time — five worded buttons said
the same thing five times and only one of them was ever right. Picking one runs whichever
toggles differ — on for the template's set, off for everything else — inside one undo
gesture, so *Make Milestone* is one Ctrl+Z however many aspects it moved. And it goes both
ways: a template reads as selected exactly when the step carries its set and nothing else,
so a combination somebody built by hand names itself — and one template may be the
**catch-all**, worn whenever no other matches, because a step with an unnamed combination
of aspects is still a step. The bar never stores which template is current; it is a
comparison on every refresh.

The face sits **beside** the strip and not in it. A widget on a ``Toolbar`` hides when
there is no room; the one control saying what the step *is* must survive every width, for
the reason the canvas's layout picker and the *Updating…* indicator sit outside theirs.
Its width is fixed to its widest name, so changing a step's kind never re-folds the strip
under it.

A toggle's ``state()`` never returns ``visible=False``, and the bar could not honour it if
it did: a strip re-shows whatever fits on every reflow. That costs nothing — *hidden means
absent; disabled means not now* already says a toggle that cannot apply is greyed, and an
aspect this build does not ship never reaches the registry at all.

The context arrives as a function, not a ``ContextService``: the panel inside the details
dialog shows a step nobody selected and names it itself, and the bar cannot tell the
difference. The host calls :meth:`refresh` on every model change it hears, because a toggle
may have changed another toggle's state — and which template matches.
"""

from collections.abc import Callable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from functools import partial
from typing import Any

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPalette
from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.action_registry import ActionRegistry, ActionSpec
from dplanner.framework.context import Context
from dplanner.framework.toolbar import Toolbar
from dplanner.framework.undo import UndoService
from dplanner.theme.icons import ICON_SIZE, glyph_painter
from dplanner.theme.tokens import CONTROL_HEIGHT, FIELD_GAP, SECONDARY_ALPHA, SECTION_GAP
from dplanner.theme.tones import button_tone


@dataclass(frozen=True)
class AspectTemplate:
    """One template the bar's dropdown offers: a name, the toggles that are on, its look."""

    label: str
    toggles: frozenset[str]  # Type toggle action ids that are on; every other one is off.
    tone: str | None = None  # A name in ``theme.tones.BODY_TONES``; None keeps the plain ink.
    glyph: str | None = None  # A name in ``theme.icons.GLYPH_ICONS``; None draws none.
    catch_all: bool = False  # Worn whenever no template matches exactly.


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
        self._selected: AspectTemplate | None = None
        # Re-derived, and said. A host that repeats the bar's answer elsewhere — the details
        # dialog's lead — cannot get it by listening to the model: applying a template ends
        # with the bar's own refresh, after the last write anybody heard.
        self.refreshed: Signal[()] = Signal("aspect_bar.refreshed")

        self.tools = Toolbar(self, dense=True)
        self.face = QToolButton(self)
        self.face.setObjectName("TemplateButton")
        self.face.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.face.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.face.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.face.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.face.setFixedHeight(CONTROL_HEIGHT)
        self._menu = QMenu(self.face)
        self.face.setMenu(self._menu)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(FIELD_GAP, FIELD_GAP, FIELD_GAP, FIELD_GAP)
        layout.setSpacing(SECTION_GAP)
        layout.addWidget(self.tools, 1)
        layout.addWidget(self.face)

        for action_id, spec in self._specs.items():
            # The words are the tooltip and the … menu's entry; the spec's own tip, where it
            # has one, stands in the tooltip so rewording a refusal never loses it.
            self._actions[action_id] = self.tools.add_verb(
                spec.label.replace("&", ""),
                spec.icon if spec.icon is not None else _no_glyph,
                partial(self._run, action_id),
                checkable=True,
                tip=spec.tip,
            )
        for template in templates:
            # Built once and parented to the bar, not rebuilt when the menu opens: templates
            # are construction data, not model data, so their actions are stable — which is
            # what lets ``template(label)`` name one and ``refresh`` tick it.
            action = QAction(template.label, self)
            action.setCheckable(True)
            action.setToolTip(self._describe(template))
            action.triggered.connect(lambda _on=False, t=template: self._apply(t))
            self._menu.addAction(action)
            self._templates.append((template, action))

        self._fit_face()
        self._reink()
        self.refresh()

    # -- what a template is made of ------------------------------------------------------------

    def _describe(self, template: AspectTemplate) -> str:
        names = [
            spec.label.replace("&", "")
            for action_id, spec in self._specs.items()
            if action_id in template.toggles
        ]
        return f"{template.label}: {', '.join(names)}" if names else template.label

    def _states(self) -> dict[str, tuple[bool, bool]]:
        """Per toggle: (enabled, checked) right now."""
        now = self._context()
        return {
            action_id: (state.enabled, bool(state.checked))
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
            for action_id, (enabled, checked) in self._states().items()
            if enabled and checked != (action_id in template.toggles)
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
        now = self._context()
        states: dict[str, tuple[bool, bool]] = {}
        for action_id, action in self._actions.items():
            spec = self._specs[action_id]
            state = spec.state(now)
            states[action_id] = (state.enabled, bool(state.checked))
            label = (state.label if state.label is not None else spec.label).replace("&", "")
            action.setEnabled(state.enabled)
            action.setChecked(bool(state.checked))
            action.setText(label)
        checked = {action_id for action_id, (_e, is_on) in states.items() if is_on}
        any_enabled = any(enabled for enabled, _c in states.values())
        # Exactly its set, and nothing else the build offers: a combination is a template.
        # What the build offers is what registered — an aspect this build lacks has no spec.
        offered = set(self._specs)
        matched = {
            template.label
            for template, _action in self._templates
            if checked == (template.toggles & offered)
        }
        selected: AspectTemplate | None = None
        for template, action in self._templates:
            action.setEnabled(any_enabled)
            is_selected = template.label in matched or (template.catch_all and not matched)
            action.setChecked(any_enabled and is_selected)
            if is_selected and selected is None:
                selected = template
        self._selected = selected if any_enabled else None
        self.face.setEnabled(any_enabled)
        self.face.setText(selected.label if selected is not None else "")
        self.face.setToolTip(
            self._describe(selected) if selected is not None else "What this step is"
        )
        self._paint_face()
        self.refreshed.emit()

    # -- ink ---------------------------------------------------------------------------------

    def _ink(self) -> QColor:
        ink = self.palette().color(QPalette.ColorRole.Text)
        ink.setAlpha(SECONDARY_ALPHA)
        return ink

    def _paint_face(self) -> None:
        """The selected template's glyph, in that template's body tone.

        The tone rides on the glyph and nothing else. A template is *always* selected —
        the catch-all guarantees it — so a wash over the face's ground would be permanently
        on and would say nothing, and DESIGN.md's *Toolbars* rules out a fill for a state
        anyway. The glyph is the one thing here that changes with the data, which is what
        makes a feature's face and a feature node one identity.
        """
        template = self._selected
        painter = glyph_painter(template.glyph) if template and template.glyph else None
        if painter is None:
            self.face.setIcon(QIcon())
            return
        tone = button_tone(template.tone) if template and template.tone else None
        self.face.setIcon(painter(tone[1] if tone is not None else self._ink()))

    def _reink(self) -> None:
        """Every template's own glyph in the menu, plus the face. The strip inks itself."""
        ink = self._ink()
        for template, action in self._templates:
            painter = glyph_painter(template.glyph) if template.glyph else None
            if painter is not None:
                tone = button_tone(template.tone) if template.tone else None
                action.setIcon(painter(tone[1] if tone is not None else ink))
        self._paint_face()

    def _fit_face(self) -> None:
        """Fix the face to its widest name, so changing a kind never re-folds the strip.

        DESIGN.md's *Toolbars*: a face that reports what is on never changes size. Left free
        this one runs from 88 px on *Step* to 115 px on *Milestone*, and a toggle could fold
        a glyph in or out of the strip beside it.
        """
        if not self._templates:
            return
        remembered = self.face.text()
        widest = 0
        for template, _action in self._templates:
            self.face.setText(template.label)
            widest = max(widest, self.face.sizeHint().width())
        self.face.setText(remembered)
        self.face.setFixedWidth(widest)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._reink()  # A glyph carries the ink it was painted in.
        elif event.type() == QEvent.Type.FontChange:
            self._fit_face()
        super().changeEvent(event)

    # -- a test's way in ---------------------------------------------------------------------

    def action(self, action_id: str) -> QAction:
        """The bar's action for one toggle id."""
        return self._actions[action_id]

    def template(self, label: str) -> QAction:
        """The bar's action for one template, by its label."""
        return next(action for template, action in self._templates if template.label == label)

    def toggle_ids(self) -> list[str]:
        """The toggle ids the strip carries, in registry order."""
        return list(self._actions)

    def template_labels(self) -> list[str]:
        return [template.label for template, _action in self._templates]

    def selected_label(self) -> str:
        """The template the step amounts to right now — what the face is wearing."""
        return self._selected.label if self._selected is not None else ""


def _no_glyph(_ink: QColor) -> QIcon:
    """A toggle whose spec carries no painter still needs a slot, or the row jumps."""
    return QIcon()
