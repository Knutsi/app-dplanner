"""Home's page: the getting-started guide, centred, over a garden that says what DPlanner does.

The Home tab's widget. It follows what it shows for as long as it lives and lets go when Qt
destroys it, which is when the tab host drops a closed tab's page.

**The guide's buttons are the verbs themselves.** Each is restated from its ``ActionSpec`` on
every context change and runs through the registry, as a menu entry does — so a verb that
needs a project greys in its own words until one is picked in the index.

**The garden is the one ornament in the application that moves** (DESIGN.md's *Focus and
motion*): the plan told as a garden, where agents rain on what is ready and it blooms
(``garden.py`` is what happens, ``garden_view.py`` how it looks). *Settings ▸ Home* turns
it off and on.
"""

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWidget

from dplanner.core.signals import Signal
from dplanner.framework.action_registry import ActionState
from dplanner.framework.activity import ActivityBase
from dplanner.framework.context import SCOPE_ACTIVITY, ContextNode, activity_uri
from dplanner.framework.row_well import RowWell, WellRow
from dplanner.framework.toolbar import action_words
from dplanner.framework.widgets import EDITOR_MEASURE, caption, centered_column
from dplanner.modules.home.garden_view import GardenView
from dplanner.modules.home.guide import GUIDE, GuideStep
from dplanner.modules.home.settings_page import garden_wanted
from dplanner.theme.tokens import CAPTION_GAP, PANEL_MARGIN

if TYPE_CHECKING:  # module.py imports this file, so the Deps arrive as a forward name.
    from dplanner.modules.home.module import HomeDeps

HOME_KIND = "home"
GUIDE_CAPTION = "Getting started"


class GuideRow(WellRow):
    """One step of the guide: its title, its words under it, and its verb at the right."""

    def __init__(self, step: GuideStep, page: "HomePage") -> None:
        super().__init__(step.title)
        self.set_note(step.words)
        self.button = self.add_button("", lambda: page.run(step))


class HomePage(QWidget):
    def __init__(
        self, deps: "HomeDeps", garden_changed: Signal[()], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._deps = deps
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget(self)
        column = QVBoxLayout(body)
        column.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        column.setSpacing(CAPTION_GAP)
        column.addStretch(1)
        column.addWidget(caption(GUIDE_CAPTION, body))
        self.guide = RowWell(body)
        # As tall as its steps, so the guide sits centred rather than filling the page.
        self.guide.setSizeAdjustPolicy(RowWell.SizeAdjustPolicy.AdjustToContents)
        column.addWidget(self.guide)
        column.addStretch(1)
        layout.addWidget(centered_column(body, EDITOR_MEASURE), 1)

        self.garden = GardenView(self)
        layout.addWidget(self.garden)

        unsubscribe = [
            deps.context.changed.connect(lambda _context: self.restate()),
            garden_changed.connect(self._show_garden),
        ]
        self.destroyed.connect(lambda: [each() for each in unsubscribe])
        self.restate()
        self._show_garden()

    # -- the guide -----------------------------------------------------------------------------

    def restate(self) -> None:
        """Say what each verb says right now: its words, whether it runs, and why not. A
        verb this build does not have (hidden, not greyed) takes its step with it."""
        context = self._deps.context.current()
        states = {step: self._deps.actions.spec(step.action).state(context) for step in GUIDE}
        self.guide.reconcile(
            [step for step in GUIDE if states[step].visible],
            lambda step: GuideRow(step, self),
            lambda step, row: self._restate(step, row, states[step]),
        )

    def _restate(self, step: GuideStep, row: GuideRow, state: ActionState) -> None:
        words, tip = action_words(self._deps.actions.spec(step.action), state)
        row.button.setText(words)
        row.button.setToolTip(tip)
        row.button.setEnabled(state.enabled)

    def run(self, step: GuideStep) -> None:
        self._deps.actions.run(step.action, self._deps.context.current())

    def _show_garden(self) -> None:
        self.garden.setVisible(garden_wanted())


class HomeActivity(ActivityBase):
    """The Home tab: the guide and the garden, kept open beside the others."""

    def __init__(self, deps: "HomeDeps", garden_changed: Signal[()]) -> None:
        self._context = deps.context
        self.uri = activity_uri(HOME_KIND)
        self.title = "Home"
        self.widget = HomePage(deps, garden_changed)

    def on_activated(self) -> None:
        self._context.set_scope(SCOPE_ACTIVITY, (ContextNode(self.uri),))
