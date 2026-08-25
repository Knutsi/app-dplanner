"""The plan: projects, phases and tasks, and the repository that stores them.

A plan is a tree of :class:`Task` nodes. The root is the project; anything with children
reads as a phase; a leaf is a task. There is deliberately no separate type for each — the
shape a plan takes is the planner's business, not the model's, and a phase that turns out to
be one piece of work should not need converting.

Beyond the tree, a task carries the four things a plan is actually made of: **who** it is
for, **when** it runs, **how big** it is, and **what it waits on**. Dependencies are the one
piece of structure that does not follow the tree — a task in one phase routinely waits on a
task in another — so they are stored as ids on the task that waits, and validated against
the tree rather than derived from it.
"""

from dplanner.domain.model import Plan, Task, TaskId
from dplanner.domain.store import PlanStore

__all__ = ["Plan", "PlanStore", "Task", "TaskId"]
