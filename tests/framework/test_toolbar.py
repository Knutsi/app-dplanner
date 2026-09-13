"""The toolbar primitive: verbs as glyphs with their words in tooltips, what no longer fits
folded into a … menu as glyph and words, a widget hidden rather than listed, one height —
and, for a strip that is a tool palette, named bands that fold whole."""

from itertools import pairwise

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QComboBox, QWidget

from dplanner.framework.action_registry import ActionRegistry, ActionSpec, MenuStructure
from dplanner.framework.context import ContextService
from dplanner.framework.toolbar import MORE, Toolbar, _Group
from dplanner.theme import apply_theme
from dplanner.theme.icons import lasso_icon, plus_icon, refresh_icon, trash_icon
from dplanner.theme.themes import DARK


@pytest.fixture
def host(app):
    widget = QWidget()
    yield widget
    widget.deleteLater()


def strip(host, app):
    bar = Toolbar(host)
    ran: list[str] = []
    bar.add_verb("Add Step", plus_icon, lambda: ran.append("add"), shortcut="Ctrl+N")
    bar.add_verb("Delete", trash_icon, lambda: ran.append("delete"))
    bar.add_divider()
    combo = QComboBox()
    combo.addItems(["All steps", "Milestones"])
    bar.add_widget(combo)
    bar.add_divider()
    bar.add_verb("Refresh", refresh_icon, lambda: ran.append("refresh"))
    bar.add_verb("Empty", refresh_icon, lambda: ran.append("empty"), checkable=True)
    host.resize(900, 60)
    host.show()
    app.processEvents()
    return bar, combo, ran


def test_a_verb_is_a_glyph_whose_words_and_shortcut_are_its_tooltip(host, app):
    bar, _combo, ran = strip(host, app)
    add, delete, *_ = bar.verbs()
    assert not add.icon().isNull() and add.text() == "Add Step"
    assert add.toolTip().startswith("Add Step") and "N" in add.toolTip()
    assert delete.toolTip() == "Delete"
    delete.setText("Delete 3 Steps")
    assert delete.toolTip() == "Delete 3 Steps"
    add.trigger()
    assert ran == ["add"]


def test_everything_fits_on_a_wide_strip_and_the_more_button_is_hidden(host, app):
    bar, combo, _ran = strip(host, app)
    bar.resize(800, bar.height())
    assert bar.hidden_items() == [] and bar._more.isHidden()
    assert not combo.isHidden()


def test_a_narrow_strip_folds_the_trailing_verbs_into_the_more_menu(host, app):
    bar, combo, ran = strip(host, app)
    bar.resize(120, bar.height())
    app.processEvents()
    assert not bar._more.isHidden() and bar._more.text() == MORE
    hidden = [action.text() for item in bar.hidden_items() for action in item.actions]
    assert "Empty" in hidden and "Refresh" in hidden
    assert combo.isHidden()  # A widget never enters the menu; it hides.
    bar._fill_more()
    listed = [action.text() for action in bar._menu.actions() if not action.isSeparator()]
    assert listed == hidden and all(
        not a.icon().isNull() for a in bar._menu.actions() if not a.isSeparator()
    )
    bar._menu.actions()[-1].trigger()
    assert ran == ["empty"]
    bar.resize(800, bar.height())
    app.processEvents()
    assert bar.hidden_items() == [] and not combo.isHidden()


def test_a_divider_never_ends_what_is_shown(host, app):
    bar, _combo, _ran = strip(host, app)
    bar.resize(200, bar.height())
    app.processEvents()
    shown = [item for item in bar._items if not item.widget.isHidden()]
    assert shown and not shown[-1].divider and not shown[0].divider


def test_a_checkable_verb_toggles_and_the_strip_asks_for_only_the_more_button(host, app):
    bar, _combo, _ran = strip(host, app)
    empty = bar.verbs()[-1]
    empty.trigger()
    assert empty.isChecked()
    assert bar.minimumSizeHint().width() == bar._more.sizeHint().width()


def test_every_control_on_a_strip_is_one_height(themed, app):
    from dplanner.theme import apply_theme
    from dplanner.theme.themes import DARK

    apply_theme(themed, DARK)
    host = QWidget()
    bar = Toolbar(host)
    bar.add_verb("Add Step", plus_icon, lambda: None)
    combo = QComboBox()
    combo.addItems(["All steps"])
    bar.add_widget(combo)
    host.resize(600, 60)
    host.show()
    app.processEvents()
    try:
        from dplanner.theme.tokens import CONTROL_HEIGHT

        button = bar._items[0].widget
        assert button.height() == combo.height() == CONTROL_HEIGHT
        assert bar._more.minimumHeight() == bar._more.maximumHeight() == CONTROL_HEIGHT
    finally:
        host.deleteLater()


def test_a_filter_button_says_when_a_filter_is_on_and_keeps_its_size(host, app):
    from dplanner.framework.toolbar import FilterButton

    button = FilterButton(host)
    heard = []
    button.changed.connect(lambda: heard.append(button.active()))
    agent = button.add_filter("agent", "Agent steps")
    button.add_filter("milestone", "Milestones")
    host.show()
    app.processEvents()
    idle = button.face.sizeHint()
    idle_icon = button.face.icon().cacheKey()
    assert not button.clear_button.isEnabled() and button.face.property("active") is False
    assert button.face.toolTip() == "Filter"
    agent.trigger()  # The menu's own click: toggles and stays open.
    assert heard == [["agent"]] and button.clear_button.isEnabled()
    assert button.face.property("active") is True and button.face.icon().cacheKey() != idle_icon
    assert button.face.toolTip() == "Filter — Agent steps"
    assert button.face.sizeHint() == idle  # The indicator is the glyph: nothing moved.
    button.set_active({"agent", "milestone"})
    assert sorted(button.active()) == ["agent", "milestone"]
    button.clear_button.click()
    assert button.active() == [] and heard[-1] == [] and not button.clear_button.isEnabled()
    assert button.face.property("active") is False
    assert all(a.isCheckable() for a in button.menu.actions())


# -- named bands ---------------------------------------------------------------------------


def banded(host, app, *, width=900):
    """Three bands of two, the way a drawing surface's strip is cut."""
    bar = Toolbar(host, dense=True)
    for label in ("Go", "Step", "Link"):
        bar.add_group(label)
        for name in ("one", "two"):
            bar.add_verb(f"{label} {name}", plus_icon, lambda: None)
    host.resize(width, 90)
    host.show()
    app.processEvents()
    bar.resize(width, bar.sizeHint().height())
    app.processEvents()
    return bar


def band_names(bar):
    return [
        group.caption.text()
        for group in bar.findChildren(_Group)
        if group.caption is not None and not group.isHidden()
    ]


def test_a_band_says_what_its_glyphs_are_for(host, app):
    bar = banded(host, app)
    assert band_names(bar) == ["Go", "Step", "Link"]
    assert bar.hidden_items() == [] and bar._more.isHidden()


def test_a_narrow_strip_folds_a_whole_band_at_a_time(host, app):
    """Half a band on the strip and half in a menu is worse than all of it in either."""
    bar = banded(host, app)
    bar.resize(140, bar.height())
    app.processEvents()
    assert band_names(bar) == ["Go"] and not bar._more.isHidden()

    bar._fill_more()
    listed = [a.text() for a in bar._menu.actions() if not a.isSeparator()]
    assert listed == ["Step one", "Step two", "Link one", "Link two"]
    # A rule where each band begins, so the menu says what the strip was saying.
    assert sum(1 for a in bar._menu.actions() if a.isSeparator()) == 1
    assert all(not a.icon().isNull() for a in bar._menu.actions() if not a.isSeparator())

    bar.resize(900, bar.height())
    app.processEvents()
    assert band_names(bar) == ["Go", "Step", "Link"]


# -- fed by the registry -------------------------------------------------------------------

MENUS = MenuStructure({"Step": ("edit",), "Graph": ("look",)})


def registry_with(*specs):
    registry = ActionRegistry(MENUS)
    for spec in specs:
        registry.register(spec)
    return registry


def test_a_registry_fed_verb_wears_the_specs_glyph_and_follows_its_state(host, app):
    picked: list[str] = []
    registry = registry_with(
        ActionSpec(
            id="steps.new",
            label="&New Step",
            menu="Step",
            group="edit",
            icon=plus_icon,
            tip="Add a step to this project",
            run=lambda _context: picked.append("new"),
        )
    )
    context = ContextService()
    bar = Toolbar(host)
    action = bar.add_action(registry, context, "steps.new")
    host.show()
    app.processEvents()

    button = bar.button_for("steps.new")
    assert button is not None and not button.icon().isNull()
    # The words lead the tooltip: a glyph that says nothing until hovered must be named.
    assert action.toolTip().startswith("New Step")
    assert "Add a step to this project" in action.toolTip()
    action.trigger()
    assert picked == ["new"]

    before = len(context.changed._slots)
    bar.dispose()
    assert len(context.changed._slots) < before


def test_a_checked_verbs_glyph_changes_ink_with_its_fill(host, app):
    """A checked button is filled with the accent; a glyph left in the quiet tone
    disappears into it, which is why the switches used to be words."""
    apply_theme(app, DARK)
    registry = registry_with(
        ActionSpec(id="steps.lasso", label="&Lasso", menu="Step", group="edit", icon=lasso_icon)
    )
    bar = Toolbar(host)
    action = bar.add_action(registry, ContextService(), "steps.lasso")
    host.show()
    app.processEvents()

    quiet = action.icon().pixmap(16, 16).toImage()
    action.setCheckable(True)
    action.setChecked(True)
    lit = action.icon().pixmap(16, 16).toImage()
    assert quiet != lit
    # And the ink it takes is the one the stylesheet writes on a checked button.
    assert bar.palette().color(QPalette.ColorRole.BrightText).name() == DARK.on_accent


def test_a_face_drops_a_band_of_the_menus_and_folds_as_a_child_menu(host, app):
    """One glyph standing for a whole band of the action table — rendered, never copied."""
    registry = registry_with(
        ActionSpec(id="canvas.frame", label="&Frame Graph", menu="Graph", group="look"),
        ActionSpec(id="canvas.snap", label="Snap to &Grid", menu="Graph", group="look"),
        ActionSpec(id="steps.new", label="&New Step", menu="Step", group="edit"),
    )
    context = ContextService()
    bar = Toolbar(host)
    face = bar.add_menu_face("Look", refresh_icon, registry, context, "Graph", group="look")
    host.show()
    app.processEvents()

    entries = bar.face_menu(face).actions()
    listed = [a.text().replace("&", "") for a in entries if not a.isSeparator()]
    assert listed == ["Frame Graph", "Snap to Grid"]  # The band, and nothing from Step.


# -- what the host takes off the strip -----------------------------------------------------


def test_a_widget_the_host_takes_off_stays_off_through_every_reflow(host, app):
    bar, combo, _ran = strip(host, app)
    bar.set_shown(combo, False)
    assert combo.isHidden()
    for width in (799, 120, 800):
        bar.resize(width, bar.height())
        app.processEvents()
        assert combo.isHidden()
    assert bar.hidden_items() == [] and bar._more.isHidden()
    shown = [item for item in bar._items if not item.widget.isHidden()]
    # The combo stood between two dividers; with it gone they must not meet.
    assert not any(a.divider and b.divider for a, b in pairwise(shown))
    bar.set_shown(combo, True)
    assert not combo.isHidden()


def test_a_verb_a_state_hides_stays_hidden_through_a_reflow(host, app):
    from dplanner.framework.action_registry import ActionState

    registry = registry_with(
        ActionSpec(
            id="steps.new",
            label="&New Step",
            menu="Step",
            group="edit",
            icon=plus_icon,
            state=lambda _context: ActionState(visible=False),
            run=lambda _context: None,
        )
    )
    bar = Toolbar(host)
    bar.add_verb("Refresh", refresh_icon, lambda: None)
    bar.add_action(registry, ContextService(), "steps.new")
    host.resize(600, 60)
    host.show()
    app.processEvents()
    for width in (500, 120, 600):
        bar.resize(width, bar.height())
        app.processEvents()
        button = bar.button_for("steps.new")
        assert button is not None and button.isHidden()
    assert bar._more.isHidden()
