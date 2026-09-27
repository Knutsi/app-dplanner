"""Which project a verb about a whole project acts on, from a context that may name none."""

from dplanner.domain.model import Library, Project, Step
from dplanner.framework.context import (
    SCOPE_ACTIVITY,
    SCOPE_SELECTION,
    Context,
    ContextNode,
    activity_uri,
    entity_uri,
    selection_uri,
)
from dplanner.framework.step_selection import focused_project


def two_projects() -> tuple[Library, Project, Project, Step]:
    library = Library()
    alpha, beta = Project(title="Alpha"), Project(title="Beta")
    for project in (alpha, beta):
        library.add_child(library.id, project)
    step = Step(title="Deploy")
    library.add_child(beta.id, step)
    return library, alpha, beta, step


def test_the_project_the_context_names_wins():
    library, alpha, _beta, step = two_projects()
    tab = ContextNode(
        activity_uri("progression", alpha.id), (("entity", entity_uri("project", alpha.id)),)
    )
    context = Context(
        {SCOPE_ACTIVITY: (tab,), SCOPE_SELECTION: (ContextNode(selection_uri("step", step.id)),)}
    )
    assert focused_project(context, library) is alpha


def test_a_view_naming_no_project_reaches_the_picked_step_s_own():
    """The Control Centre spans every project and names none; Show in ▸ Order from one of
    its rows means that row's project."""
    library, _alpha, beta, step = two_projects()
    context = Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step.id)),)})
    assert focused_project(context, library) is beta
    assert focused_project(Context({}), library) is None
