"""Which step, or which steps, a verb acts on — read from the context, in one place.

Every verb that acts on a step asks one of two questions, and a second copy of either is
how two verbs come to disagree about what "this step" means. :func:`focused_step` is *the
one thing to act on*: the selection, else whatever the activity is about, which is what
makes a menu entry work identically whether the user picked a row or simply has the step
open. :func:`chosen_steps` is the same rule for a verb that can act on several at once —
Delete, Cut, Copy, Duplicate, Isolate and Run Agent all read it, so a lasso means the same
thing to all of them.

:func:`focused_project` is the project a verb about a whole project acts on: the one the
context names, else the focused step's own — so a view spanning several projects, which
names none, still reaches the project of the step picked in it.
"""

from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.framework.context import Context


def focused_step(context: Context, library: Library) -> Step | None:
    """The step the context focuses, if the library still has it."""
    step_id = context.focus_entity("step")
    if step_id is None or not library.has(step_id):
        return None
    return library.step(step_id)


def chosen_steps(context: Context, library: Library) -> list[StepId]:
    """Every selected step that still exists, else the one the activity is about."""
    chosen = [s for s in context.selected_entities("step") if library.has(s)]
    if chosen:
        return chosen
    step_id = context.focus_entity("step")
    return [step_id] if step_id is not None and library.has(step_id) else []


def focused_project(context: Context, library: Library) -> Project | None:
    """The project the context names, else the focused step's, if the library has it."""
    project_id = context.focus_entity("project")
    if project_id is not None and library.has(project_id):
        return library.project(project_id)
    step = focused_step(context, library)
    return None if step is None else library.project_of(step.id)
