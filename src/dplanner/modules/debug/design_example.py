"""Debug ▸ Design Example: the design system built from its primitives, to be looked at
and copied from.

Two surfaces over sample data, nothing saved. The *modal* is a :class:`DialogFrame`
carrying a form (captions over fields, a hint glyph, a validation note), a :class:`Table`
(a glyph column, a two-line cell, a numeric column, a heading, a tinted row) and every
signalling state — an *Updating…* indicator on a demo debouncer, a status line in each
tone, a determinate progress bar and a refused primary. The *tab* is the same table under
a control strip with the indicator at its right, outside the » overflow, and an empty
state that trades places with the table.

A developer bringing a surface up (DESIGN.md's *Bringing a surface up*) opens these beside
their own and copies what differs; ``docs/screenshots/f1-design-example/`` holds them
rendered in both themes. Neither reads the model, so neither follows a project.
"""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, ContextService, activity_uri
from dplanner.framework.debounce import SETTLE_MS, Debounced, DebounceService
from dplanner.framework.dialog import DialogFrame
from dplanner.framework.signalling import StatusLine, UpdatingIndicator
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import control_bar
from dplanner.framework.widgets import EmptyState, caption, note
from dplanner.theme.icons import ICON_SIZE, beaker_icon, info_icon, layers_icon, step_icon, tag_icon
from dplanner.theme.themes import Theme
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP
from dplanner.theme.tones import HIGHLIGHT_FILL

DESIGN_TABLE_KIND = "design_table"
DEMO_DELAY_MS = 1500  # Long enough to see the indicator; a real view settles in 300.
NO_ROWS = "No steps match. Every row is sample data; Add Rows puts them back."
COLUMNS = (
    Column("Step", glyph=True, detail=True, resize="interactive"),
    Column("Days", numeric=True),
    Column("Status"),
)
FILTERS = ("All steps", "Agent steps", "Milestones")


@dataclass(frozen=True)
class SampleRow:
    kind: str  # "milestone" | "feature" | "step" | "test" — decides the glyph and the tint.
    key: str
    title: str
    days: str
    status: str
    agent: bool = False


SAMPLE: tuple[tuple[str, tuple[SampleRow, ...]], ...] = (
    (
        "Improvements #1",
        (
            SampleRow(
                "feature",
                "F1",
                "Design system: guidelines and primitives",
                "2 d",
                "in progress",
                True,
            ),
            SampleRow(
                "step", "S6", "Step details: toggles left, templates right", "1 d", "pending", True
            ),
            SampleRow(
                "test",
                "S9",
                "Boards: Ready to start launches every ready agent",
                "1.5 d",
                "pending",
                True,
            ),
            SampleRow("milestone", "M2", "Improvements #1", "", "pending"),
        ),
    ),
    (
        "Improvements #2",
        (
            SampleRow(
                "step", "S12", "Specs tab as CRUD with markdown tools", "2 d", "pending", True
            ),
            SampleRow("step", "S11", "Documentation compiled by an agent", "1 d", "done"),
            SampleRow("milestone", "M3", "Improvements #2", "", "pending"),
        ),
    ),
)
_GLYPHS = {"milestone": tag_icon, "feature": layers_icon, "step": step_icon, "test": beaker_icon}


def sample_cells(row: SampleRow, ink: QColor) -> list[Cell]:
    done = row.status == "done"
    return [
        Cell(
            row.title,
            detail=row.key,
            glyph=_GLYPHS[row.kind](ink),
            emphasis=row.kind == "milestone",
        ),
        Cell(row.days, secondary=done),
        Cell(row.status, secondary=done),
    ]


KEY_ROLE = int(Qt.ItemDataRole.UserRole) + 60  # The host's own role: which sample row.
Groups = list[tuple[str, list[SampleRow]]]


def sample_groups() -> Groups:
    """A mutable copy of the sample, for a surface whose verbs add and remove rows."""
    return [(heading, list(rows)) for heading, rows in SAMPLE]


def fill_sample(table: Table, ink: QColor, keep: str, groups: Groups | None = None) -> None:
    """The sample rows under their headings, narrowed by one of ``FILTERS``."""
    table.clear_rows()
    for heading, rows in groups if groups is not None else sample_groups():
        shown = [
            row
            for row in rows
            if keep == FILTERS[0]
            or (keep == FILTERS[1] and row.agent)
            or (keep == FILTERS[2] and row.kind == "milestone")
        ]
        if not shown:
            continue
        table.add_heading(heading)
        for row in shown:
            tint = HIGHLIGHT_FILL if row.kind == "milestone" else None
            table.add_row(sample_cells(row, ink), tint=tint, data={KEY_ROLE: row.key})
    table.fit_columns()


def ink_of(widget: QWidget) -> QColor:
    return widget.palette().color(QPalette.ColorRole.Text)


def captioned(title: str, parent: QWidget, hint: str = "") -> QWidget:
    """A caption over a block, with the standing convention behind an info glyph."""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(FIELD_GAP)
    layout.addWidget(caption(title, row))
    if hint:
        glyph = QLabel(row)
        glyph.setPixmap(info_icon(ink_of(parent)).pixmap(ICON_SIZE, ICON_SIZE))
        glyph.setToolTip(hint)
        layout.addWidget(glyph)
    layout.addStretch(1)
    return row


class DesignExampleDialog(DialogFrame):
    """The modal: a form, a table and every signalling state on one frame."""

    def __init__(self, debounce: DebounceService, parent: QWidget | None = None) -> None:
        super().__init__(
            "Design Example",
            parent,
            lead="Every rule DESIGN.md states, on one modal — sample data, nothing is saved.",
            size=(760, 760),
        )
        body = self.body_layout

        form = QVBoxLayout()
        form.setSpacing(CAPTION_GAP)
        body.addLayout(form)  # Added before it is filled: a parentless layout leaks items.
        form.addWidget(
            captioned("Name", self.body, "A step's name is what its card shows; the key is dealt.")
        )
        self.name = QLineEdit("Build the modal", self.body)
        form.addWidget(self.name)
        form.addSpacing(FIELD_GAP)
        form.addWidget(captioned("Branch", self.body))
        self.branch = QLineEdit("agent/f7-build-the-modal", self.body)
        form.addWidget(self.branch)
        self.problem = StatusLine(self.body)
        self.problem.say("A branch of that name already exists on the remote", "error")
        form.addWidget(self.problem)
        form.addSpacing(FIELD_GAP)
        form.addWidget(captioned("Summary", self.body))
        self.summary = QLineEdit(self.body)
        self.summary.setPlaceholderText("What this step delivers (optional)")
        form.addWidget(self.summary)

        body.addWidget(captioned("Steps", self.body))
        self.table = Table(COLUMNS, parent=self.body)
        fill_sample(self.table, ink_of(self.body), FILTERS[0])
        body.addWidget(self.table, 1)

        signals = QVBoxLayout()
        signals.setSpacing(CAPTION_GAP)
        body.addLayout(signals)
        signals.addWidget(captioned("Signalling", self.body))
        strip = QHBoxLayout()
        strip.setSpacing(FIELD_GAP)
        signals.addLayout(strip)
        self.change_button = QToolButton(self.body)
        self.change_button.setObjectName("ToolbarButton")
        self.change_button.setText("Change something")
        strip.addWidget(self.change_button)
        strip.addStretch(1)
        self.updating = UpdatingIndicator(self.body)
        strip.addWidget(self.updating)
        self._recompute_soon = Debounced(
            self._recompute, DEMO_DELAY_MS, parent=self, service=debounce
        )
        self.updating.follow(self._recompute_soon)
        self.change_button.clicked.connect(self._recompute_soon.trigger)
        self.lines = [StatusLine(self.body) for _ in range(4)]
        for line, (words, tone) in zip(
            self.lines,
            (
                ("12 pages, fetched today", "info"),
                ("Reading the repository…", "busy"),
                ("Connected — this account can read the space", "ok"),
                ("gh is not installed — branches and PRs are typed, not picked", "error"),
            ),
            strict=True,
        ):
            line.say(words, tone)  # type: ignore[arg-type]
            signals.addWidget(line)
        signals.addWidget(note("Publishing 2 of 5 repositories", self.body))
        self.progress = QProgressBar(self.body)
        self.progress.setRange(0, 5)
        self.progress.setValue(2)
        self.progress.setTextVisible(False)
        signals.addWidget(self.progress)
        self.refuse_switch = QCheckBox(
            "Refuse the primary, with the reason in the footer", self.body
        )
        self.refuse_switch.toggled.connect(
            lambda on: self.refuse("Pick a repository first" if on else None)
        )
        signals.addWidget(self.refuse_switch)

        self.add_button("Delete Sample", self._delete, destructive=True)
        self.add_dismiss()
        self.set_primary("Apply", self.accept)

    def _recompute(self) -> None:
        fill_sample(self.table, ink_of(self.body), FILTERS[0])

    def _delete(self) -> None:
        self.status.say("Nothing was deleted — this is sample data", "info")


class DesignExampleActivity(ActivityBase):
    """The tab: the table under a control strip, the indicator at the strip's right."""

    def __init__(
        self, context: ContextService, debounce: DebounceService, theme: ThemeService
    ) -> None:
        self._context = context
        self.uri = activity_uri(DESIGN_TABLE_KIND)
        self.title = "Design Example"

        self.widget = QWidget()
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(SECTION_GAP)

        strip = QHBoxLayout()
        strip.setSpacing(FIELD_GAP)
        layout.addLayout(strip)  # Before it is filled: a parentless layout leaks its items.
        self.controls = control_bar(self.widget)
        # The verbs first — creation, then what acts on the picked rows, greyed until there
        # are any and worded with the count — then the view's own controls.
        self.add_button = QToolButton(self.controls)
        self.add_button.setObjectName("ToolbarButton")
        self.add_button.setText("Add Step")
        self.controls.addWidget(self.add_button)
        self.delete_button = QToolButton(self.controls)
        self.delete_button.setObjectName("ToolbarButton")
        self.delete_button.setText("Delete")
        self.delete_button.setEnabled(False)
        self.controls.addWidget(self.delete_button)
        self.controls.addSeparator()
        self.filter = QComboBox(self.controls)
        self.filter.addItems(FILTERS)
        self.controls.addWidget(self.filter)
        self.controls.addSeparator()
        self.refresh_button = QToolButton(self.controls)
        self.refresh_button.setObjectName("ToolbarButton")
        self.refresh_button.setText("Refresh")
        self.controls.addWidget(self.refresh_button)
        self.controls.addSeparator()
        self.empty_toggle = QToolButton(self.controls)
        self.empty_toggle.setObjectName("ToolbarButton")
        self.empty_toggle.setText("Empty")
        self.empty_toggle.setCheckable(True)
        self.controls.addWidget(self.empty_toggle)
        strip.addWidget(self.controls, 1)
        self.updating = UpdatingIndicator(self.widget)
        strip.addWidget(self.updating)  # Outside the bar: the » overflow never swallows it.

        self.table = Table(COLUMNS, selection="extended", parent=self.widget)
        layout.addWidget(self.table, 1)
        self.empty = EmptyState(
            parent=self.widget, action=("Add Rows", self._add_rows), stands_in_for=self.table
        )
        layout.addWidget(self.empty, 1)

        self._groups = sample_groups()
        self._minted = 0
        self._refresh_soon = Debounced(
            self._refresh, SETTLE_MS, parent=self.widget, service=debounce
        )
        self.updating.follow(self._refresh_soon)
        self.add_button.clicked.connect(self._add_step)
        self.delete_button.clicked.connect(self._delete_picked)
        self.table.itemSelectionChanged.connect(self._reword_verbs)
        self.filter.currentIndexChanged.connect(lambda _index: self._refresh_soon.trigger())
        self.refresh_button.clicked.connect(self._refresh_soon.trigger)
        self.empty_toggle.toggled.connect(lambda _on: self._refresh_soon.trigger())
        self._unsubscribe = theme.changed.connect(self._on_theme)
        self._refresh()

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))

    def close(self) -> None:
        self._unsubscribe()

    def _on_theme(self, _theme: Theme) -> None:
        self._refresh()  # The glyphs carry the ink they were painted in.

    def _add_rows(self) -> None:
        self.empty_toggle.setChecked(False)

    def picked_keys(self) -> list[str]:
        rows = sorted({item.row() for item in self.table.selectedItems()})
        keys = (self.table.item(row, 0) for row in rows)
        return [str(item.data(KEY_ROLE)) for item in keys if item is not None]

    def _reword_verbs(self) -> None:
        count = len(self.picked_keys())
        self.delete_button.setEnabled(count > 0)
        self.delete_button.setText(
            "Delete" if count == 0 else "Delete Step" if count == 1 else f"Delete {count} Steps"
        )

    def _add_step(self) -> None:
        self._minted += 1
        _heading, rows = self._groups[-1]
        key = f"S{40 + self._minted}"
        rows.append(SampleRow("step", key, "A step added from the strip", "0.5 d", "pending", True))
        self._refresh_soon.trigger()

    def _delete_picked(self) -> None:
        gone = set(self.picked_keys())
        for _heading, rows in self._groups:
            rows[:] = [row for row in rows if row.key not in gone]
        self._refresh_soon.trigger()

    def _refresh(self) -> None:
        if self.empty_toggle.isChecked():
            self.table.clear_rows()
            self.empty.say(NO_ROWS)
            self._reword_verbs()
            return
        self.empty.say("")
        fill_sample(self.table, ink_of(self.widget), self.filter.currentText(), self._groups)
        self._reword_verbs()


def glyph_for(kind: str, ink: QColor) -> QIcon:
    return _GLYPHS[kind](ink)


__all__ = [
    "COLUMNS",
    "DESIGN_TABLE_KIND",
    "FILTERS",
    "DesignExampleActivity",
    "DesignExampleDialog",
    "fill_sample",
    "glyph_for",
]
