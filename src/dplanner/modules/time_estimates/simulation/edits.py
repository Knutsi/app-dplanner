"""What the simulator changes in a plan, each from the day it is made: a re-budget.

In the window each is an ordinary write, made today, and the model re-plans from tomorrow —
so nothing needs to remember when it was made. The simulator keeps the day because it plays
history back: the world makes the change on that day, and the team really changes with it.
"""

from dataclasses import dataclass
from datetime import date

from dplanner.modules.time_estimates.simulation.frames import PlanState
from dplanner.modules.time_estimates.simulation.world import BudgetChange


@dataclass(frozen=True)
class Budget:
    humans: int
    agents: int
    efficiency: float


@dataclass(frozen=True)
class BudgetEdit:
    day: date
    budget: Budget


def budget_of(state: PlanState) -> Budget:
    humans, agents = state.team
    return Budget(humans, agents, state.efficiency)


def rebudget(
    edits: tuple[BudgetEdit, ...], day: date, budget: Budget, before: Budget
) -> tuple[BudgetEdit, ...]:
    """Re-budget on ``day``. It replaces any change already made that day; one that leaves
    the budget as it stood (``before``) is no change at all, and is dropped."""
    others = [edit for edit in edits if edit.day != day]
    kept = others if budget == before else [*others, BudgetEdit(day, budget)]
    return tuple(sorted(kept, key=lambda edit: edit.day))


def world_budgets(edits: tuple[BudgetEdit, ...], begin: date) -> tuple[BudgetChange, ...]:
    """The re-budgets as the world takes them: in days since work began."""
    return tuple(
        BudgetChange(
            after=(edit.day - begin).days,
            humans=edit.budget.humans,
            agents=edit.budget.agents,
            efficiency=edit.budget.efficiency,
        )
        for edit in edits
    )
