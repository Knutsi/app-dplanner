"""Actions as a dialog of checkboxes: the fifth presenter, beside the menu bar, palette,
toolbar and pop-up menu.

The one rule the other four already follow: a surface **renders** the registry, never a copy
of it. A dialog that listed aspects from a hand-maintained table would be a second place to
add an aspect and would be wrong the first time somebody forgot. So this reads the same specs
the *Type* submenu renders, through the same context, and running one goes through
``ActionRegistry.run`` — which means every toggle keeps its own undo command and its own
confirmation, and this file knows nothing about any of them.

The same policy as ``action_menu``: **hidden means the capability is absent, disabled means
not right now**, and a disabled row keeps its state's label, which is where a toggle says why
("Estimate — a milestone has no work of its own"). That is the whole mechanism behind "some
step types can never carry this aspect": a predicate on the owning module's spec, and nothing
here changes.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.action_registry import ActionRegistry
from dplanner.framework.context import Context

# DESIGN.md: 20 px dialog margins, 12 between sections, 8 inside one; a rich row's two
# lines sit 4 px apart.
DIALOG_MARGIN = 20
SECTION_GAP = 12
ROW_GAP = 8
LINE_GAP = 4
DIALOG_WIDTH = 420
DIALOG_MAX_HEIGHT = 520


class _Row(QWidget):
    """One toggle: a checkbox naming the aspect, and its tip as the line beneath.

    DESIGN.md's rich-row rule — the *what* on line one, the *why* on line two, never run
    together into one blob. The tip is the same sentence the menu shows as a status tip, so
    the two presenters teach the same thing.
    """

    def __init__(self, label: str, tip: str, checked: bool, enabled: bool) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LINE_GAP)

        self.box = QCheckBox(label.replace("&", ""), self)
        self.box.setChecked(checked)
        self.box.setEnabled(enabled)
        layout.addWidget(self.box)

        if tip:
            note = QLabel(tip, self)
            note.setObjectName("InspectorNote")
            note.setWordWrap(True)
            note.setEnabled(enabled)
            # Indented under the box's text rather than under its indicator, so the two
            # lines read as one row.
            note.setContentsMargins(self.box.iconSize().width() + ROW_GAP, 0, 0, 0)
            layout.addWidget(note)


class TogglesDialog(QDialog):
    """Every toggle in one (menu, submenu), as checkboxes over the current context.

    Applied as they are clicked rather than on a button: each toggle is already one
    undoable command, so a Cancel that had to unwind several would be a second, worse undo
    stack. The button is Close.

    The context arrives as a **function**, re-asked on every read, so a caller whose target
    is not the window's selection — a panel hosted in a modal, showing a step nobody
    selected — hands over one naming its own, and the specs cannot tell the difference.
    """

    def __init__(
        self,
        actions: ActionRegistry,
        context: Callable[[], Context],
        *,
        menu: str,
        submenu: str,
        title: str,
        note: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._actions = actions
        self._context = context
        self._specs = [
            spec for spec in actions.all_specs() if spec.menu == menu and spec.submenu == submenu
        ]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN, DIALOG_MARGIN)
        outer.setSpacing(SECTION_GAP)

        if note:
            caption = QLabel(note, self)
            caption.setObjectName("InspectorNote")
            caption.setWordWrap(True)
            outer.addWidget(caption)

        body = QWidget(self)
        self._rows_layout = QVBoxLayout(body)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(ROW_GAP)
        self._rows_layout.addStretch(1)

        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(body)
        outer.addWidget(area, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.rows: dict[str, _Row] = {}
        self._rebuild()
        # Sized rather than hinted: a `sizeHint` override would be one more Qt camelCase
        # exception for the linter to carry, and the height is a clamp, not a preference.
        self.resize(DIALOG_WIDTH, min(self.sizeHint().height(), DIALOG_MAX_HEIGHT))

    def _rebuild(self) -> None:
        """Read every spec's state and lay the rows out again.

        Wholesale rather than in place, because one toggle can change another's state — a
        milestone that refuses an estimate is exactly that — and re-asking every spec is
        the only answer that cannot go stale.
        """
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
        self.rows = {}
        now = self._context()
        for spec in self._specs:
            state = spec.state(now)
            if not state.visible:
                continue  # Hidden means this build has no such capability at all.
            row = _Row(
                state.label if state.label is not None else spec.label,
                spec.tip,
                bool(state.checked),
                state.enabled,
            )
            row.box.clicked.connect(lambda _on=False, sid=spec.id: self._toggle(sid))
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
            self.rows[spec.id] = row

    def _toggle(self, action_id: str) -> None:
        self._actions.run(action_id, self._context())
        # A toggle may have asked a question and been answered no, so the checkbox is
        # re-read from the model rather than believed.
        self._rebuild()
