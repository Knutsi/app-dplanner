"""The starter plan a brand-new workspace is seeded with.

A plan that opens to nothing is hard to judge and harder to demo. Creating a workspace
therefore writes a small, real one — enough that the tree, the editor, the properties panel
and the dependency list all have something to show.

Keep it short. It is a greeting, not a tutorial.
"""

from dplanner.core.storage.provider import StorageProvider
from dplanner.domain.model import Plan, Task
from dplanner.domain.store import PlanStore

WELCOME = """\
This is a plan. Every task is a folder on disk, so the whole thing can be read with any
editor and kept in version control alongside whatever it is planning.

A task with children reads as a phase; a leaf is work. Estimates roll up, and a phase is
done when everything under it is — so the plan cannot disagree with itself.
"""


def create_sample(storage: StorageProvider) -> None:
    """Write a starter plan through ``storage``. The caller loads it afterwards."""
    root = Task(title="New project", description=WELCOME)
    plan = Plan(root, title="New project")

    discovery = Task(title="Discovery", status="doing")
    plan.add_task(root.id, discovery)
    interviews = Task(title="Interviews", status="done", estimate_days=3, assignee="me")
    plan.add_task(discovery.id, interviews)
    findings = Task(title="Write up findings", estimate_days=1, assignee="me")
    plan.add_task(discovery.id, findings)

    build = Task(title="Build", notes="Not started until discovery lands.")
    plan.add_task(root.id, build)
    first = Task(title="First slice", estimate_days=5)
    plan.add_task(build.id, first)

    # The one piece of structure that does not follow the tree.
    plan.set_dependencies(first.id, [findings.id])
    plan.set_dependencies(findings.id, [interviews.id])

    PlanStore(storage).create(plan)
