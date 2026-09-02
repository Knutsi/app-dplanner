"""AspectBar: templates worded left, every toggle glyphed right, and the two agreeing."""

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
from dplanner.framework.aspect_bar import AspectBar, AspectTemplate
from dplanner.framework.context import Context
from dplanner.framework.undo import UndoService

MENUS = MenuStructure({"Step": ("classify", "edit")})


def glyph(colour: QColor) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(colour)
    return QIcon(pixmap)


class Flip:
    """A command over the toggles' dict of flags — the model, in miniature."""

    def __init__(self, on, action_id):
        self.on = on
        self.action_id = action_id

    def text(self):
        return self.action_id

    def redo(self, _document):
        self.on[self.action_id] = not self.on[self.action_id]

    def undo(self, _document):
        self.on[self.action_id] = not self.on[self.action_id]

    def merge_with(self, _other):
        return False


class Toggles:
    """A registry of Type toggles, each flipping through the undo stack like a real one."""

    def __init__(self, *ids: str) -> None:
        self.on: dict[str, bool] = dict.fromkeys(ids, False)
        self.enabled = True
        self.undo = UndoService(object())
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
            self.undo.push(Flip(self.on, action_id))

        return flip


@pytest.fixture
def toggles():
    return Toggles("milestone", "feature", "estimate", "description", "docs")


TEMPLATES = (
    AspectTemplate("Step", frozenset({"estimate", "description"})),
    AspectTemplate("Milestone", frozenset({"milestone", "description"}), tone="highlight"),
    AspectTemplate("Feature", frozenset({"feature", "description"}), glyph="layers"),
)


def make_bar(toggles, templates=TEMPLATES):
    return AspectBar(toggles.registry, lambda: Context({}), templates, undo=toggles.undo)


def test_templates_go_left_in_the_given_order_and_every_toggle_goes_right(app, toggles):
    bar = make_bar(toggles)
    assert bar.template_labels() == ["Step", "Milestone", "Feature"]
    assert bar.toggle_ids() == ["milestone", "feature", "estimate", "description", "docs"]
    with pytest.raises(KeyError):
        bar.action("elsewhere")  # Not in the submenu, so not on the bar.


def test_a_template_describes_itself_in_the_toggles_words(app, toggles):
    bar = make_bar(toggles)
    assert bar.template("Milestone").toolTip() == "Milestone: Milestone, Description"


def test_triggering_a_toggle_runs_the_registry_and_rereads_every_state(app, toggles):
    bar = make_bar(toggles)
    bar.action("feature").trigger()
    assert toggles.on["feature"] is True
    assert bar.action("feature").isChecked() is True
    # A change made behind the bar's back reaches it on refresh, not before.
    toggles.on["docs"] = True
    assert bar.action("docs").isChecked() is False
    bar.refresh()
    assert bar.action("docs").isChecked() is True


def test_applying_a_template_moves_every_differing_toggle_as_one_undo_step(app, toggles):
    """On for the template's set, off for everything else — and one Ctrl+Z puts it all
    back, however many toggles it took, each still the owning verb's own command."""
    bar = make_bar(toggles)
    toggles.on.update({"estimate": True, "description": True, "docs": True})
    bar.refresh()

    bar.template("Milestone").trigger()
    assert toggles.on == {
        "milestone": True,
        "feature": False,
        "estimate": False,
        "description": True,
        "docs": False,
    }
    assert toggles.undo.undo_text() == "Make Milestone"
    toggles.undo.undo()
    assert toggles.on == {
        "milestone": False,
        "feature": False,
        "estimate": True,
        "description": True,
        "docs": True,
    }
    assert not toggles.undo.can_undo()


def test_a_combination_is_a_template_and_only_an_exact_one(app, toggles):
    """A template reads as selected when the step carries its set and nothing else — so a
    combination built by hand lights up the template it amounts to, and one extra aspect
    puts it out again."""
    bar = make_bar(toggles)
    assert not any(bar.template(label).isChecked() for label in bar.template_labels())

    bar.action("estimate").trigger()
    bar.action("description").trigger()
    assert bar.template("Step").isChecked() is True
    assert bar.template("Milestone").isChecked() is False

    bar.action("docs").trigger()
    assert bar.template("Step").isChecked() is False

    bar.action("docs").trigger()
    bar.action("estimate").trigger()
    bar.action("milestone").trigger()
    assert bar.template("Milestone").isChecked() is True
    assert bar.template("Step").isChecked() is False


def test_applying_the_matching_template_changes_nothing(app, toggles):
    bar = make_bar(toggles)
    bar.template("Step").trigger()
    before = dict(toggles.on)
    bar.template("Step").trigger()
    assert toggles.on == before
    assert toggles.undo.undo_text() == "Make Step"  # Only the first application is a step.


def test_a_disabled_state_greys_toggles_and_templates_alike(app, toggles):
    bar = make_bar(toggles)
    toggles.enabled = False
    bar.refresh()
    assert not bar.action("feature").isEnabled()
    assert bar.action("feature").isVisible()
    assert not bar.template("Step").isEnabled()
    assert not bar.template("Step").isChecked()


def test_words_left_glyphs_right_and_no_focus_anywhere(app, toggles):
    from PySide6.QtCore import Qt

    bar = make_bar(toggles)
    bar.paint("#808080")
    template = bar.templates_bar.widgetForAction(bar.template("Milestone"))
    toggle = bar.toggles_bar.widgetForAction(bar.action("docs"))
    assert isinstance(template, QToolButton) and isinstance(toggle, QToolButton)
    assert template.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert toggle.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert template.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert not bar.action("docs").icon().isNull()
    assert not bar.template("Feature").icon().isNull()  # A named glyph.
    assert bar.template("Step").icon().isNull()  # No glyph named, none drawn.
    # A toned template wears its colour when checked; an untoned one keeps the theme's rule.
    assert "background-color" in template.styleSheet()
    assert bar.templates_bar.widgetForAction(bar.template("Step")).styleSheet() == ""


def test_a_bar_too_narrow_for_its_templates_grows_the_overflow_button(app, toggles):
    """Overflow is QToolBar's own »: the actions that no longer fit move into its menu."""
    bar = make_bar(toggles)
    bar.paint("#808080")  # Glyphs, as the app paints them: an unpainted toggle shows words.
    bar.show()
    bar.resize(700, 48)
    app.processEvents()
    extension = bar.templates_bar.findChild(QToolButton, "qt_toolbar_ext_button")
    assert extension is not None
    assert not extension.isVisible()

    bar.resize(200, 48)
    app.processEvents()
    assert extension.isVisible()
    bar.close()
