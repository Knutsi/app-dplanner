"""Plans with stacks in them, and the walk that proves a stack edit safe — shared by the
stack tests, with no Qt.

Membership is written the way ``stack_edits`` writes it: ``"stack"`` on every member's
entry and a seat on the first member alone.
"""

from dplanner.domain.model import Library, Project, Step
from dplanner.modules.project_editor.positions import MODULE_ID, write_member, write_position
from dplanner.modules.project_editor.stacks import link_rule, read_stacks, stray_links

# How far down the column each next default member sits: its card and the gap, rounded up
# onto the grid.
PITCH = 104.0


def plan(*titles):
    library = Library()
    library.link_rules = (link_rule,)
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    steps = {}
    for title in titles:
        steps[title] = Step(title=title)
        library.add_child(project.id, steps[title])
    return library, project, steps


def link(library, steps, waiter, *sources):
    library.set_edges(steps[waiter].id, "requires", [steps[s].id for s in sources])


def stack(library, steps, *titles, seat=None, stack_id="s1"):
    """Membership as the stack verbs write it: the key on every member, a seat on the first."""
    first, *rest = titles
    head = write_position(*seat, stack=stack_id) if seat else write_member(stack_id)
    library.set_module_data(steps[first].id, MODULE_ID, head)
    for title in rest:
        library.set_module_data(steps[title].id, MODULE_ID, write_member(stack_id))


def stacked(seat=None):
    """start → a → b → c → after, with a, b and c stacked, and a loose step beside start."""
    library, project, steps = plan("start", "a", "b", "c", "after", "beside")
    link(library, steps, "a", "start")
    link(library, steps, "b", "a")
    link(library, steps, "c", "b")
    link(library, steps, "after", "c")
    link(library, steps, "beside", "start")
    stack(library, steps, "a", "b", "c", seat=seat)
    return library, project, steps


def edges(project):
    """Every edge the project's steps hold, as ``(waiter, kind, source)``."""
    return {
        (step.id, kind, source)
        for step in project.steps
        for kind, sources in step.edges.items()
        for source in sources
    }


def state(project):
    """What a stack edit may change: the steps there are, their links and their canvas
    entries."""
    return (
        tuple(step.id for step in project.steps),
        frozenset(edges(project)),
        tuple(sorted((step.id, repr(step.module_data.get(MODULE_ID))) for step in project.steps)),
    )


def has_cycle(project):
    waits = {step.id: step.edges.get("requires", []) for step in project.steps}
    done, open_ = set(), set()

    def visit(step_id):
        if step_id in open_:
            return True
        if step_id in done or step_id not in waits:
            return False
        open_.add(step_id)
        found = any(visit(source) for source in waits[step_id])
        open_.discard(step_id)
        done.add(step_id)
        return found

    return any(visit(step_id) for step_id in waits)


def walk(library, project, command):
    """The rewire proof, run: the command redone and undone whole and then one part at a
    time, every graph on the way a part of the one before or the one after and free of
    cycles, and every pass landing exactly where the last one did. Returns the state after.
    """
    before = state(project)
    old = edges(project)
    command.redo(library)
    after = state(project)
    new = edges(project)
    command.undo(library)
    assert state(project) == before
    for part in command.commands:
        part.redo(library)
        now = edges(project)
        assert now <= old or now <= new, f"{type(part).__name__} left a graph that is neither"
        assert not has_cycle(project)
    assert state(project) == after
    for part in reversed(command.commands):
        part.undo(library)
        now = edges(project)
        assert now <= old or now <= new, f"undoing {type(part).__name__} left neither"
        assert not has_cycle(project)
    assert state(project) == before
    command.redo(library)
    assert state(project) == after
    return after


def assert_one_line(library, project):
    """Every stack is one line — no gap, no stray link — and every ``requires`` link in the
    plan is one the stack rule would allow if it were made now."""
    for found in read_stacks(project.steps):
        assert not found.gaps, found
        assert not stray_links(found, project.steps), found
    for step in project.steps:
        sources = list(step.edges.get("requires", []))
        for source in sources:
            step.edges["requires"] = [other for other in sources if other != source]
            try:
                assert link_rule(library, step.id, "requires", source) is None, (
                    step.title,
                    library.step(source).title,
                )
            finally:
                step.edges["requires"] = sources
