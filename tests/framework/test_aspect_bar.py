"""AspectBar: one submenu's toggles as two toolbars, kinds worded left and facets glyphed right."""

import pytest
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QToolButton

from dplanner.framework.action_registry import (
    DISABLED,
    ActionRegistry,
    ActionSpec,
    ActionState,
    MenuStructure,
)
from dplanner.framework.aspect_bar import AspectBar, KindButton
from dplanner.framework.context import Context

MENUS = MenuStructure({"Step": ("classify", "edit")})


def glyph(colour: QColor) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(colour)
    return QIcon(pixmap)


class Toggles:
    """A registry of Type toggles over a dict of flags — the model, in miniature."""

    def __init__(self, *ids: str) -> None:
        self.on: dict[str, bool] = dict.fromkeys(ids, False)
        self.enabled = True
        self.registry = ActionRegistry(MENUS)
        for order, action_id in enumerate(ids):
            self.registry.register(
                ActionSpec(
                    id=action_id,
                    label=f"&{action_id.title()}",
                    menu="Step",
                    group="classify",
                    submenu="Type",
                    order=order,
                    icon=glyph,
                    tip=f"toggle {action_id}",
                    state=self._state_of(action_id),
                    run=self._flip_of(action_id),
                )
            )
        self.registry.register(
            ActionSpec(
                id="elsewhere",
                label="Elsewhere",
                menu="Step",
                group="edit",
                state=lambda _c: ActionState(),
                run=lambda _c: None,
            )
        )

    def _state_of(self, action_id):
        def state(_context):
            return ActionState(checked=self.on[action_id]) if self.enabled else DISABLED

        return state

    def _flip_of(self, action_id):
        def flip(_context):
            self.on[action_id] = not self.on[action_id]

        return flip


@pytest.fixture
def toggles():
    return Toggles("milestone", "feature", "estimate", "ticket", "docs")


KINDS = (KindButton("feature", "feature"), KindButton("milestone"))


def make_bar(toggles, kinds=KINDS):
    return AspectBar(toggles.registry, lambda: Context({}), kinds)


def test_kinds_go_left_in_the_given_order_and_the_rest_go_right(app, toggles):
    bar = make_bar(toggles)
    assert bar.ids(bar.kinds_bar) == ["feature", "milestone"]
    assert bar.ids(bar.facets_bar) == ["estimate", "ticket", "docs"]
    with pytest.raises(KeyError):
        bar.action("elsewhere")  # Not in the submenu, so not on the bar.


def test_a_kind_named_but_not_registered_is_simply_absent(app, toggles):
    bar = make_bar(toggles, kinds=(KindButton("feature"), KindButton("agent")))
    assert bar.ids(bar.kinds_bar) == ["feature"]


def test_triggering_runs_the_registry_and_rereads_every_state(app, toggles):
    bar = make_bar(toggles)
    bar.action("feature").trigger()
    assert toggles.on["feature"] is True
    assert bar.action("feature").isChecked() is True
    # A change made behind the bar's back reaches it on refresh, not before.
    toggles.on["docs"] = True
    assert bar.action("docs").isChecked() is False
    bar.refresh()
    assert bar.action("docs").isChecked() is True


def test_a_disabled_state_greys_the_button_and_keeps_it(app, toggles):
    bar = make_bar(toggles)
    toggles.enabled = False
    bar.refresh()
    assert not bar.action("feature").isEnabled()
    assert bar.action("feature").isVisible()


def test_words_left_glyphs_right_and_no_focus_anywhere(app, toggles):
    from PySide6.QtCore import Qt

    bar = make_bar(toggles)
    bar.paint("#808080")
    kind = bar.kinds_bar.widgetForAction(bar.action("feature"))
    facet = bar.facets_bar.widgetForAction(bar.action("docs"))
    assert isinstance(kind, QToolButton) and isinstance(facet, QToolButton)
    assert kind.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert facet.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert kind.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert not bar.action("docs").icon().isNull()
    # A toned kind wears its colour when checked; an untoned one keeps the theme's rule.
    assert "background-color" in kind.styleSheet()
    assert bar.kinds_bar.widgetForAction(bar.action("milestone")).styleSheet() == ""


def test_a_bar_too_narrow_for_its_kinds_grows_the_overflow_button(app, toggles):
    """Overflow is QToolBar's own »: the actions that no longer fit move into its menu."""
    bar = make_bar(toggles)
    bar.show()
    bar.resize(600, 48)
    app.processEvents()
    extension = bar.kinds_bar.findChild(QToolButton, "qt_toolbar_ext_button")
    assert extension is not None
    assert not extension.isVisible()

    bar.resize(140, 48)
    app.processEvents()
    assert extension.isVisible()
    bar.close()
