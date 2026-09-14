"""Debug ▸ Design Example: the design system built from its primitives, to be looked at
and copied from.

Three surfaces over sample data, nothing saved. The *modal* is a :class:`DialogFrame` —
title in the body, a footer band — carrying a form (captions over fields, a hint glyph, a
validation note), a :class:`Table` (a glyph column, a two-line cell, a numeric column, a
heading, a milestone row wearing its key badge) and every signalling state: an *Updating…*
indicator and a :class:`Spinner` on a demo debouncer, a status line in each tone, a
determinate progress bar and a refused primary. The *tab* is the same table under a
:class:`Toolbar` — glyph verbs that fold into a … menu, a :class:`FilterButton`, a combo,
the indicator at the strip's right — with verbs worded by the selection and an empty state
that trades places with the table. The *toolbars* tab is every shape a strip of verbs
comes in, one under the next: the flat strip, the tool palette's named bands of squares,
the same palette with no room so the bands fold into the ``…`` menu, and the dense strip
that answers a question rather than offering verbs.

A developer bringing a surface up (DESIGN.md's *Bringing a surface up*) opens these beside
their own and copies what differs; ``docs/screenshots/f1-design-example/`` holds them
rendered in both themes. Neither reads the model, so neither follows a project.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
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
from dplanner.framework.notices import Notice, NoticeBar
from dplanner.framework.signalling import Spinner, StatusLine, UpdatingIndicator
from dplanner.framework.table import Cell, Column, Table
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import FilterButton, Toolbar
from dplanner.framework.widgets import EmptyState, caption, captioned, ink_of, note
from dplanner.theme.icons import (
    ICON_SIZE,
    beaker_icon,
    connect_icon,
    edit_icon,
    find_icon,
    frame_icon,
    isolate_icon,
    key_badge_icon,
    layers_icon,
    list_icon,
    options_icon,
    plus_icon,
    refresh_icon,
    shield_icon,
    spark_icon,
    step_icon,
    tag_icon,
    ticket_icon,
    trash_icon,
    unlink_icon,
)
from dplanner.theme.palettes import PALETTES, shades
from dplanner.theme.themes import Theme
from dplanner.theme.tokens import CAPTION_GAP, FIELD_GAP, PANEL_MARGIN, SECTION_GAP
from dplanner.theme.tones import HIGHLIGHT_FILL, recoloured

DESIGN_TABLE_KIND = "design_table"
DESIGN_TOOLBARS_KIND = "design_toolbars"
# What a palette is cut down to, to show a band folding rather than describe it.
NO_ROOM = 300
# The sample's milestones wear real shades of the default map, dealt by place in the
# sequence, because that is what a milestone wears everywhere in the application now —
# a reference that showed one constant purple would teach the rule that was replaced.
SAMPLE_SHADES = shades(PALETTES[0], 3)
DEMO_DELAY_MS = 1500  # Long enough to see the indicator; a real view settles in 300.
NO_ROWS = "No steps match. Every row is sample data; Add Rows puts them back."
COLUMNS = (
    Column("Step", glyph=True, detail=True, resize="interactive"),
    Column("Days", numeric=True),
    Column("Status"),
)
FILTERS = (("agent", "Agent steps"), ("milestone", "Milestones"), ("done", "Done"))
GROUPINGS = ("Grouped by milestone", "Flat")

# A glyph painter: the colour in, the icon out.
GlyphPainter = Callable[[QColor], QIcon]

# The bands the palette example wears: three of two or three, so a fold has something to
# take. Sample verbs, not registered ones — this page is about the shape.
BANDS: tuple[tuple[str, tuple[tuple[str, GlyphPainter], ...]], ...] = (
    ("Go", (("Find", find_icon), ("Frame", frame_icon))),
    ("Step", (("New", plus_icon), ("Rename", edit_icon), ("Delete", trash_icon))),
    ("Link", (("Connect", connect_icon), ("Unlink", unlink_icon), ("Isolate", isolate_icon))),
)
# And what a dense strip answers with: what the thing on screen carries, two of them on.
TOGGLES: tuple[tuple[str, GlyphPainter], ...] = (
    ("Milestone", tag_icon),
    ("Feature", layers_icon),
    ("Agent", spark_icon),
    ("Test", beaker_icon),
    ("Check", shield_icon),
    ("Ticket", ticket_icon),
)


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
# The sample's milestones, in roadmap order — what ``sample_shade`` deals along.
_MILESTONES = tuple(row for _heading, rows in SAMPLE for row in rows if row.kind == "milestone")


def sample_shade(row: SampleRow) -> str:
    """A sample milestone's shade — ``M1`` the deepest, in the order the roadmap runs."""
    place = [found.key for found in _MILESTONES].index(row.key)
    return SAMPLE_SHADES[place]


def sample_cells(row: SampleRow, ink: QColor) -> list[Cell]:
    done = row.status == "done"
    milestone = row.kind == "milestone"
    # A milestone is known by its key, so the key badge stands where the glyph would and
    # the second line says what the row gathers rather than the key again — in that
    # milestone's own shade of the project's colour map.
    glyph = key_badge_icon(row.key, sample_shade(row)) if milestone else _GLYPHS[row.kind](ink)
    detail = "gathers every step above it" if milestone else row.key
    return [
        Cell(row.title, detail=detail, glyph=glyph, emphasis=milestone),
        Cell(row.days, secondary=done),
        Cell(row.status, secondary=done),
    ]


KEY_ROLE = int(Qt.ItemDataRole.UserRole) + 60  # The host's own role: which sample row.
Groups = list[tuple[str, list[SampleRow]]]


def sample_groups() -> Groups:
    """A mutable copy of the sample, for a surface whose verbs add and remove rows."""
    return [(heading, list(rows)) for heading, rows in SAMPLE]


def matches(row: SampleRow, active: set[str]) -> bool:
    """No filter on shows everything; several on show what matches any of them."""
    return (
        not active
        or ("agent" in active and row.agent)
        or ("milestone" in active and row.kind == "milestone")
        or ("done" in active and row.status == "done")
    )


def fill_sample(
    table: Table,
    ink: QColor,
    active: set[str] = frozenset(),  # type: ignore[assignment]
    groups: Groups | None = None,
    *,
    grouped: bool = True,
) -> None:
    """The sample rows, narrowed by the active ``FILTERS`` keys, under their headings or flat."""
    table.clear_rows()
    for heading, rows in groups if groups is not None else sample_groups():
        shown = [row for row in rows if matches(row, active)]
        if not shown:
            continue
        if grouped:
            table.add_heading(heading)
        for row in shown:
            tint = (
                recoloured(HIGHLIGHT_FILL, sample_shade(row)) if row.kind == "milestone" else None
            )
            table.add_row(sample_cells(row, ink), tint=tint, data={KEY_ROLE: row.key})
    table.fit_columns()


class DesignExampleDialog(DialogFrame):
    """The modal: a form, a table and every signalling state on one frame."""

    def __init__(self, debounce: DebounceService, parent: QWidget | None = None) -> None:
        super().__init__("Design Example", parent, size=(760, 760))
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
        fill_sample(self.table, ink_of(self.body))
        body.addWidget(self.table, 1)

        signals = QVBoxLayout()
        signals.setSpacing(CAPTION_GAP)
        body.addLayout(signals)
        signals.addWidget(captioned("Signalling", self.body))
        strip = QHBoxLayout()
        strip.setSpacing(FIELD_GAP)
        signals.addLayout(strip)
        # A button that starts work carries a glyph, and the glyph turns while the work
        # runs: the slot is always there, so nothing moves.
        self.change_button = QToolButton(self.body)
        self.change_button.setObjectName("ToolbarButton")
        self.change_button.setText("Change something")
        self.change_button.setIcon(spark_icon(ink_of(self.body)))
        self.change_button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.change_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        strip.addWidget(self.change_button)
        strip.addStretch(1)
        self.updating = UpdatingIndicator(self.body)
        strip.addWidget(self.updating)
        self._recompute_soon = Debounced(
            self._recompute, DEMO_DELAY_MS, parent=self, service=debounce
        )
        self.updating.follow(self._recompute_soon)
        self.spinner = Spinner(self.body).attach(self.change_button)
        self.spinner.follow(self._recompute_soon)
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
        # Standing notices: a fact that holds until it stops holding. In the application
        # this bar sits over the whole window's content (framework/main_window.py) — it is
        # here so the two shapes can be compared with the lines above them. Busy with a
        # declared count, and the same fact once it has gone quiet, with its one verb.
        self.notices = NoticeBar(self.body)
        self.notices.show_notice(
            Notice(
                id="demo.agent",
                words="An agent is at work on Payments — linking the steps · 8 of 20"
                " · heard just now",
                tone="busy",
                busy=True,
                fraction=0.4,
            )
        )
        self.notices.show_notice(
            Notice(
                id="demo.conflict",
                words="2 entries changed here and outside — this window is not saving"
                " until settled",
                tone="error",
                action="Settle…",
            )
        )
        signals.addWidget(self.notices)
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
        fill_sample(self.table, ink_of(self.body))

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
        self.controls = Toolbar(self.widget)
        # The verbs first — creation, then what acts on the picked rows, greyed until there
        # are any and worded with the count — then the view's own controls. Glyphs, with
        # the words in the tooltips; what no longer fits folds into the … menu.
        self.add_action = self.controls.add_verb("Add Step", plus_icon, self._add_step)
        self.delete_action = self.controls.add_verb("Delete", trash_icon, self._delete_picked)
        self.delete_action.setEnabled(False)
        self.controls.add_divider()
        self.filter = FilterButton()
        for key, text in FILTERS:
            self.filter.add_filter(key, text)
        self.controls.add_widget(self.filter)
        self.group = QComboBox()
        self.group.addItems(GROUPINGS)
        self.controls.add_widget(self.group)
        self.controls.add_divider()
        self.refresh_action = self.controls.add_verb(
            "Refresh", refresh_icon, self._refresh_soon_trigger
        )
        self.empty_action = self.controls.add_verb(
            "Show the empty state", list_icon, self._refresh_soon_trigger, checkable=True
        )
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
        self.spinner = Spinner(self.widget).attach(self.refresh_action)
        self.spinner.follow(self._refresh_soon)
        self.table.itemSelectionChanged.connect(self._reword_verbs)
        self.filter.changed.connect(self._refresh_soon.trigger)
        self.group.currentIndexChanged.connect(lambda _index: self._refresh_soon.trigger())
        self._unsubscribe = theme.changed.connect(self._on_theme)
        self._refresh()

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))

    def close(self) -> None:
        self._unsubscribe()

    def _on_theme(self, _theme: Theme) -> None:
        self._refresh()  # The glyphs carry the ink they were painted in.

    def _refresh_soon_trigger(self) -> None:
        self._refresh_soon.trigger()

    def _add_rows(self) -> None:
        self.empty_action.setChecked(False)
        self._refresh_soon.trigger()

    def picked_keys(self) -> list[str]:
        rows = sorted({item.row() for item in self.table.selectedItems()})
        keys = (self.table.item(row, 0) for row in rows)
        return [str(item.data(KEY_ROLE)) for item in keys if item is not None]

    def _reword_verbs(self) -> None:
        count = len(self.picked_keys())
        self.delete_action.setEnabled(count > 0)
        self.delete_action.setText(
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
        if self.empty_action.isChecked():
            self.table.clear_rows()
            self.empty.say(NO_ROWS)
            self._reword_verbs()
            return
        self.empty.say("")
        fill_sample(
            self.table,
            ink_of(self.widget),
            set(self.filter.active()),
            self._groups,
            grouped=self.group.currentIndex() == 0,
        )
        self._reword_verbs()


class DesignExampleToolbars(ActivityBase):
    """The tab: every shape a strip of verbs comes in, one under the next.

    DESIGN.md's *Toolbars*, built rather than described. Nothing here reaches a registry —
    the verbs are plain slots, as the modal's are — because what this page is for is the
    shape: what a glyph button looks like, what a band looks like, what happens when there
    is no room for one, and how a strip that answers a question differs from a strip that
    offers verbs.
    """

    def __init__(self, context: ContextService, theme: ThemeService) -> None:
        self._context = context
        self.uri = activity_uri(DESIGN_TOOLBARS_KIND)
        self.title = "Design Example Toolbars"

        self.widget = QWidget()
        column = QVBoxLayout(self.widget)
        column.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        column.setSpacing(SECTION_GAP)

        self.verbs = self._verbs_strip()
        self._block(
            column,
            "A strip of verbs",
            self.verbs,
            "Glyphs with their words in the tooltip, a divider between groups, a filter "
            "among them. What no longer fits folds into the … menu from the right; a widget "
            "never enters it — it hides when there is no room.",
        )

        self.palette = self._banded_strip()
        self._block(
            column,
            "A tool palette",
            self.palette,
            "A strip cut into named bands: a band's glyphs sit close and read as one set, "
            "the bands stand apart with a hairline between them, and each carries its name. "
            "A band's buttons are squares — a palette is a grid of targets of one size. A "
            "family of verbs is one button and its arrow; a band of the menus is one face, "
            "which runs no verb of its own.",
        )

        self.folded = self._banded_strip()
        self.folded.setFixedWidth(NO_ROOM)
        self._block(
            column,
            "…and the same palette with no room",
            self.folded,
            "A band leaves the strip whole and is listed in the … menu as glyph and words, "
            "with a rule where each band begins. Half a band on the strip and half in a "
            "menu says less than either.",
        )

        self.dense = self._dense_strip()
        self._block(
            column,
            "A dense strip",
            self.dense,
            "Not verbs but an answer — what the thing on screen carries. It is read as one "
            "set rather than aimed at one at a time, so it keeps the height and takes the "
            "width back from the sides: a strip that folds stops answering its question.",
        )
        column.addStretch(1)

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))

    def close(self) -> None:
        for bar in (self.verbs, self.palette, self.folded, self.dense):
            bar.dispose()

    def _block(self, column: QVBoxLayout, title: str, bar: Toolbar, remark: str) -> None:
        column.addWidget(caption(title, self.widget))
        row = QHBoxLayout()
        column.addLayout(row)  # Before it is filled: a parentless layout leaks its items.
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(FIELD_GAP)
        # A strip cut short to show a fold keeps its own width and stays at the left; the
        # rest take the page's, which is what puts them under one another.
        cut_short = bar.maximumWidth() == bar.minimumWidth()
        row.addWidget(bar, 0 if cut_short else 1)
        if cut_short:
            row.addStretch(1)
        column.addWidget(note(remark, self.widget))

    def _verbs_strip(self) -> Toolbar:
        bar = Toolbar(self.widget)
        bar.add_verb("Add Step", plus_icon, lambda: None, shortcut="Ctrl+N")
        bar.add_verb("Delete", trash_icon, lambda: None)
        bar.add_divider()
        funnel = FilterButton()
        for key, text in FILTERS:
            funnel.add_filter(key, text)
        bar.add_widget(funnel)
        bar.add_divider()
        bar.add_verb("Refresh", refresh_icon, lambda: None)
        return bar

    def _banded_strip(self) -> Toolbar:
        bar = Toolbar(self.widget, dense=True)
        for band, verbs in BANDS:
            bar.add_group(band)
            for label, glyph in verbs:
                bar.add_verb(label, glyph, lambda: None)
        bar.add_group("Options")
        bar.add_verb("How the graph is drawn", options_icon, lambda: None)
        return bar

    def _dense_strip(self) -> Toolbar:
        bar = Toolbar(self.widget, dense=True)
        for label, glyph in TOGGLES:
            toggle = bar.add_verb(label, glyph, lambda: None, checkable=True)
            toggle.setChecked(label in ("Milestone", "Agent"))
        return bar


def glyph_for(kind: str, ink: QColor) -> QIcon:
    return _GLYPHS[kind](ink)


__all__ = [
    "COLUMNS",
    "DESIGN_TABLE_KIND",
    "DESIGN_TOOLBARS_KIND",
    "FILTERS",
    "DesignExampleActivity",
    "DesignExampleDialog",
    "DesignExampleToolbars",
    "fill_sample",
    "glyph_for",
]
