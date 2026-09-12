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
from dplanner.framework.toolbar import MORE
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
    AspectTemplate("Step", frozenset({"estimate", "description"}), catch_all=True),
    AspectTemplate("Milestone", frozenset({"milestone", "description"}), tone="highlight"),
    AspectTemplate("Feature", frozenset({"feature", "description"}), glyph="layers"),
)


def make_bar(toggles, templates=TEMPLATES):
    return AspectBar(toggles.registry, lambda: Context({}), templates, undo=toggles.undo)


def test_templates_come_in_the_given_order_and_every_toggle_goes_on_the_strip(app, toggles):
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
    bar.action("description").trigger()
    bar.action("milestone").trigger()
    assert bar.template("Milestone").isChecked() is True
    assert bar.template("Step").isChecked() is False

    bar.action("docs").trigger()
    assert bar.template("Milestone").isChecked() is False


def test_the_catch_all_template_is_lit_whenever_no_other_matches(app, toggles):
    """A combination no template names is still a step: the catch-all lights for it, for
    nothing at all, and for its own set — and yields the moment another template matches."""
    bar = make_bar(toggles)
    assert bar.template("Step").isChecked() is True  # Nothing on at all.
    bar.action("milestone").trigger()
    bar.action("docs").trigger()
    assert bar.template("Step").isChecked() is True  # Milestone + docs is nobody's set.
    assert bar.template("Milestone").isChecked() is False
    bar.action("docs").trigger()
    bar.action("description").trigger()
    assert bar.template("Milestone").isChecked() is True
    assert bar.template("Step").isChecked() is False


def test_without_a_catch_all_an_unnamed_combination_lights_nothing(app, toggles):
    bar = make_bar(toggles, templates=TEMPLATES[1:])
    bar.action("docs").trigger()
    assert not any(bar.template(label).isChecked() for label in bar.template_labels())


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
    assert not bar.template("Step").isEnabled()
    assert not bar.template("Step").isChecked()
    assert not bar.face.isEnabled()
    assert bar.selected_label() == ""  # Nothing to be, with no step to be it.


def test_glyphs_on_the_strip_one_worded_face_and_no_focus_anywhere(app, toggles):
    from PySide6.QtCore import Qt

    bar = make_bar(toggles)
    toggle = bar.tools.findChildren(QToolButton)[0]
    assert bar.face.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert bar.face.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert toggle.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert bar.face.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert toggle.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert not bar.action("docs").icon().isNull()
    assert not bar.template("Feature").icon().isNull()  # A named glyph.
    # The tone rides on the glyph; nothing on this bar carries a stylesheet of its own.
    assert bar.styleSheet() == ""
    assert all(button.styleSheet() == "" for button in bar.findChildren(QToolButton))


def test_the_face_is_named_for_what_it_offers_and_the_menu_says_which_is_on(app, toggles):
    """The face says *Template* and never changes; which one the step amounts to is the
    ticked entry. Derived on every refresh, never stored."""
    bar = make_bar(toggles)
    assert bar.face.text() == "Template"
    assert bar.selected_label() == "Step"  # The catch-all: nothing else matches.
    assert bar.template("Step").isChecked()

    toggles.on.update(milestone=True, description=True, estimate=False)
    bar.refresh()
    assert bar.face.text() == "Template"  # Unmoved.
    assert bar.selected_label() == "Milestone"
    assert bar.template("Milestone").isChecked()
    assert not bar.template("Step").isChecked()

    toggles.on.update(docs=True)
    bar.refresh()
    # One aspect too many, and it is the catch-all again.
    assert bar.selected_label() == "Step"


def test_every_template_carries_its_glyph_into_the_menu(app, toggles):
    """The tone rides on the glyph — a feature's entry and a feature node are one identity —
    and the face carries none, so nothing on it moves as the step changes."""
    bar = make_bar(toggles)
    assert not bar.template("Feature").icon().isNull()
    assert bar.face.icon().isNull()


def test_the_strip_is_dense_so_a_dock_wide_row_of_toggles_fits(app, toggles):
    """The row answers *what does this step carry*, so it packs rather than folds.

    At the verb strip's own metrics a 45 px glyph button seats five of the ten Type toggles
    in the width the step panel can actually be (its minimum is 479 px, set by its tab
    pages, which leaves the strip ~356); dense is 29 px and seats all ten.
    """
    bar = make_bar(toggles)
    buttons = [b for b in bar.tools.findChildren(QToolButton) if b.text() != MORE]
    assert bar.tools.property("dense") is True
    assert all(b.sizeHint().width() <= 32 for b in buttons)


def test_a_narrow_bar_folds_toggles_into_the_menu_and_never_the_face(app, toggles):
    """The … takes the strip from the right; the one control saying what the step *is*
    survives every width, which is why it sits beside the strip and not in it."""
    bar = make_bar(toggles)
    bar.show()
    bar.resize(700, 48)
    app.processEvents()
    assert bar.tools.hidden_items() == []
    assert bar.face.isVisible()

    bar.resize(200, 48)
    app.processEvents()
    assert bar.tools.hidden_items() != []  # Something folded…
    assert bar.face.isVisible()  # …and it was never the face.
    bar.close()
