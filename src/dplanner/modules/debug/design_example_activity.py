"""Debug ▸ Design Examples ▸ Modal, Table and Toolbars: the design system built from its
primitives, to be looked at and copied from.

Three surfaces over sample data (``design_sample.py``), nothing saved. The *modal*
(``design_example_dialog.py``) is a :class:`DialogFrame` —
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
rendered in both themes. None reads the model, so none follows a project.
``design_rows_activity.py`` is the fourth page, and the one that also shows a defect on purpose.
"""

from collections.abc import Callable

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, ContextService, activity_uri
from dplanner.framework.debounce import SETTLE_MS, Debounced, DebounceService
from dplanner.framework.popover import PopoverButton
from dplanner.framework.segmented import Segmented
from dplanner.framework.signalling import Spinner, UpdatingIndicator
from dplanner.framework.slider_row import SliderRow
from dplanner.framework.table import Table
from dplanner.framework.theme_service import ThemeService
from dplanner.framework.toolbar import FilterButton, Toolbar
from dplanner.framework.widgets import EmptyState, caption, ink_of, note
from dplanner.modules.debug.design_sample import (
    KEY_ROLE,
    TICKED_COLUMNS,
    SampleRow,
    fill_sample,
    sample_groups,
)
from dplanner.theme.icons import (
    beaker_icon,
    connect_icon,
    edit_icon,
    find_icon,
    frame_icon,
    isolate_icon,
    layers_icon,
    list_icon,
    options_icon,
    plus_icon,
    refresh_icon,
    shield_icon,
    spark_icon,
    tag_icon,
    ticket_icon,
    trash_icon,
    unlink_icon,
)
from dplanner.theme.themes import Theme
from dplanner.theme.tokens import FIELD_GAP, PANEL_MARGIN, SECTION_GAP

DESIGN_TABLE_KIND = "design_table"
DESIGN_TOOLBARS_KIND = "design_toolbars"
# What a palette is cut down to, to show a band folding rather than describe it.
NO_ROOM = 300
NO_ROWS = "No steps match. Every row is sample data; Add Rows puts them back."
FILTERS = (("agent", "Agent steps"), ("milestone", "Milestones"), ("done", "Done"))
GROUPINGS = ("Grouped by milestone", "Folding groups", "Flat")

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

        self.table = Table(TICKED_COLUMNS, selection="extended", parent=self.widget)
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
        self.table.menu_requested.connect(self._drop_row_menu)
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

    def row_menu(self, row: int) -> QMenu:
        """What one row can be told: the row picked alone first, so the menu and the strip
        agree about what it is about, then glyph and words, greyed with the reason where a
        verb cannot run — never dropped, or the menu changes shape from row to row."""
        self.table.pick_row(row)
        (key,) = self.picked_keys()
        sample = next(one for _heading, rows in self._groups for one in rows if one.key == key)
        ink = ink_of(self.widget)
        menu = QMenu(self.table)
        words = "Run Agent" if sample.agent else "Run Agent — not an agent step"
        run = menu.addAction(spark_icon(ink), words)
        run.setEnabled(sample.agent)
        menu.addSeparator()
        menu.addAction(trash_icon(ink), "Delete Step").triggered.connect(self._delete_picked)
        return menu

    def _drop_row_menu(self, row: int, at: QPoint) -> None:
        menu = self.row_menu(row)
        menu.exec(at)
        menu.deleteLater()

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
            grouped=self.group.currentIndex() < 2,
            folding=self.group.currentIndex() == 1,
            ticked=True,
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
            "which runs no verb of its own. Two ways of looking at one surface are a "
            "segmented pair in the band they are about, keeping their words.",
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

        self.settings = self._settings_strip()
        self._block(
            column,
            "A strip that holds settings",
            self.settings,
            "The pages of the surface are a segmented group: every choice at once, the one "
            "shown lit. A setting carries its value on its face and drops a popover for what a "
            "menu cannot hold — buttons that stay lit, a slider that keeps its keys — closed "
            "by a click outside it, as a menu is.",
        )
        column.addStretch(1)

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))

    def close(self) -> None:
        for bar in (self.verbs, self.palette, self.folded, self.dense, self.settings):
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
        # Two ways of looking at one surface, named at once, in the band they are about —
        # the graph's Free | Waves. Words in a band of squares: the primitive keeps them.
        bar.add_group("Arrange")
        view = Segmented(
            [
                ("free", "Free", "Your own arrangement"),
                ("waves", "Waves", "Every step in the column of its wave"),
            ],
            bar,
        )
        view.set_value("waves")
        bar.add_widget(view)
        bar.add_group("Options")
        bar.add_verb("How the graph is drawn", options_icon, lambda: None)
        return bar

    def _settings_strip(self) -> Toolbar:
        bar = Toolbar(self.widget)
        self.pages = Segmented(
            [
                (page, page.title(), f"The {page} page")
                for page in ("milestones", "work", "calendar")
            ],
            bar,
        )
        self.pages.set_value("work")
        bar.add_widget(self.pages)
        bar.add_divider()
        self.budget = PopoverButton("Budget · 1p/2a · 50%", bar, tip="Who works on the plan")
        body = self.budget.popover.body
        for label, counts, picked in (("People", (1, 2, 3), 1), ("Agents", (1, 2, 3, 4), 2)):
            body.addWidget(caption(label, self.budget.popover))
            choices = Segmented([(n, str(n), "") for n in counts], self.budget.popover)
            choices.set_value(picked)
            body.addWidget(choices)
        body.addWidget(caption("Focus", self.budget.popover))
        focus = QComboBox(self.budget.popover)
        focus.addItems([f"{percent}%" for percent in range(10, 101, 5)])
        focus.setCurrentText("50%")
        body.addWidget(focus)
        body.addWidget(note("From today on; the days before keep theirs.", self.budget.popover))
        bar.add_widget(self.budget)
        self.history = PopoverButton("History", bar, tip="The tab as it was recorded earlier")
        days = SliderRow(
            self.history.popover, earlier="The record before", later="The record after"
        )
        days.set_count(12)
        days.set_value(11)
        self.history.popover.body.addWidget(days)
        self.history.popover.body.addWidget(note("today", self.history.popover))
        bar.add_widget(self.history)
        return bar

    def _dense_strip(self) -> Toolbar:
        bar = Toolbar(self.widget, dense=True)
        for label, glyph in TOGGLES:
            toggle = bar.add_verb(label, glyph, lambda: None, checkable=True)
            toggle.setChecked(label in ("Milestone", "Agent"))
        return bar
