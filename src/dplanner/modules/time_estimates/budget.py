"""The Budget: who works on the plan and how much of their day, from today on.

A face on the tab's strip — ``Budget · 1p/2a · 50%`` — that drops a popover: people and, when
the plan has agent steps, agents as segmented counts, and the focus as a list in steps of
five. A pick is announced at once (:attr:`BudgetButton.chosen`) and the host writes it as
one undoable command; it applies from today on, because the model re-plans only forward and
``schedule.write_project`` keeps the focus work already in flight ran at. It replaced the
staffing matrix and the focus spinbox: the question the tab answers is when *this* team
lands the plan, and trying another team is choosing it.
"""

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QWidget

from dplanner.domain.schedule import format_date
from dplanner.framework.popover import PopoverButton
from dplanner.framework.segmented import Segmented
from dplanner.framework.widgets import caption, note
from dplanner.modules.time_estimates.schedule import AGENTS, HUMANS

FOCUS_STEP = 5  # Percent: the focus a person gives, as the list offers it.


def people(count: int) -> str:
    return f"{count} {'person' if count == 1 else 'people'}"


def agents(count: int) -> str:
    return f"{count} agent{'' if count == 1 else 's'}"


class BudgetButton(PopoverButton):
    """``chosen`` carries ``(humans, agents, efficiency)`` whenever a pick changes one."""

    chosen = Signal(int, int, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Budget", parent)
        panel = self.popover
        body = panel.body
        body.addWidget(caption("People", panel))
        self.people = Segmented([(count, str(count), people(count)) for count in HUMANS], panel)
        body.addWidget(self.people)
        self.agents_caption = caption("Agents", panel)
        body.addWidget(self.agents_caption)
        self.agents = Segmented([(count, str(count), agents(count)) for count in AGENTS], panel)
        body.addWidget(self.agents)
        body.addWidget(caption("Focus", panel))
        self.focus = QComboBox(panel)
        self.focus.setToolTip("How much of a person's working day this project gets")
        body.addWidget(self.focus)
        self.from_when = note("", panel)
        body.addWidget(self.from_when)
        self._team = (HUMANS[0], AGENTS[0])
        self._efficiency = 0.5
        self._loading = False
        self.people.picked.connect(lambda count: self._pick(humans=count))
        self.agents.picked.connect(lambda count: self._pick(agents=count))
        self.focus.currentIndexChanged.connect(lambda _index: self._pick_focus())

    def show_budget(
        self, team: tuple[int, int], efficiency: float, *, has_agent_steps: bool, today: date
    ) -> None:
        """The stored budget on the face and in the popover — placing it, never a pick."""
        self._team, self._efficiency = team, efficiency
        humans, bots = team
        percent = round(efficiency * 100)
        self.setText(
            f"Budget · {humans}p/{bots}a · {percent}%"
            if has_agent_steps
            else f"Budget · {humans}p · {percent}%"
        )
        crew = people(humans) + (f" and {agents(bots)}" if has_agent_steps else "")
        self.setToolTip(f"{crew}, at {percent}% focus — a change applies from today on")
        self._loading = True
        try:
            self.people.set_value(humans)
            self.agents.set_value(bots)
            self.agents_caption.setVisible(has_agent_steps)
            self.agents.setVisible(has_agent_steps)
            choices = sorted({*range(10, 101, FOCUS_STEP), percent})
            self.focus.clear()
            for value in choices:
                self.focus.addItem(f"{value}%", value)
            self.focus.setCurrentIndex(self.focus.findData(percent))
        finally:
            self._loading = False
        self.from_when.setText(f"From {format_date(today, today)} on; the days before keep theirs.")

    def _pick(self, *, humans: int | None = None, agents: int | None = None) -> None:
        if self._loading:
            return
        team = (humans or self._team[0], agents or self._team[1])
        if team != self._team:
            self.chosen.emit(team[0], team[1], self._efficiency)

    def _pick_focus(self) -> None:
        if self._loading or self.focus.currentData() is None:
            return
        efficiency = int(self.focus.currentData()) / 100
        if round(efficiency * 100) != round(self._efficiency * 100):
            self.chosen.emit(self._team[0], self._team[1], efficiency)
