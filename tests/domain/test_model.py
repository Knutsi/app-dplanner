"""The plan model: one signal per mutation, roll-ups that cannot lie, dependencies that
cannot form a cycle."""

import pytest

from dplanner.domain.model import Plan, Task, TextEdit, unique_folder_name


@pytest.fixture
def plan():
    root = Task(title="Project")
    plan = Plan(root)
    discovery = Task(title="Discovery")
    plan.add_task(root.id, discovery)
    plan.add_task(discovery.id, Task(title="Interviews", estimate_days=3))
    plan.add_task(discovery.id, Task(title="Write-up", estimate_days=1))
    plan.add_task(root.id, Task(title="Build", estimate_days=5))
    return plan


def ids(plan, title):
    return next(task.id for task in plan.tasks() if task.title == title)


def test_ids_are_stable_and_unique(plan):
    all_ids = [task.id for task in plan.tasks()]
    assert len(set(all_ids)) == len(all_ids)


def test_setting_a_title_emits_once_with_its_origin(plan):
    seen = []
    plan.title_changed.connect(lambda task_id, origin: seen.append((task_id, origin)))
    marker = object()
    task_id = ids(plan, "Build")
    plan.set_title(task_id, "Ship", marker)
    assert seen == [(task_id, marker)]


def test_setting_the_same_value_emits_nothing(plan):
    seen = []
    plan.field_changed.connect(lambda *args: seen.append(args))
    task_id = ids(plan, "Build")
    plan.set_field(task_id, "status", "todo")
    assert seen == []


def test_every_change_marks_something_dirty(plan):
    marks = []
    plan.dirty.connect(lambda owner_id, aspect: marks.append(aspect))
    task_id = ids(plan, "Build")
    plan.set_title(task_id, "Ship")
    plan.set_field(task_id, "status", "doing")
    plan.set_notes(task_id, "note")
    plan.set_description(task_id, "what it is")
    plan.set_module_data(task_id, "m", {"a": 1})
    assert marks == ["meta", "meta", "notes", "description", "module_data"]


def test_an_unknown_field_is_refused(plan):
    with pytest.raises(ValueError, match="not an editable value field"):
        plan.set_field(ids(plan, "Build"), "colour", "red")


def test_an_unknown_status_is_refused(plan):
    with pytest.raises(ValueError, match="not a status"):
        plan.set_field(ids(plan, "Build"), "status", "nearly")


# -- what makes it a plan rather than a tree of notes -----------------------------------------


def test_a_phase_is_done_when_everything_under_it_is(plan):
    """Derived, not stored — so a phase cannot disagree with its contents."""
    discovery = plan.task(ids(plan, "Discovery"))
    assert not discovery.is_done()
    for child in discovery.children:
        plan.set_field(child.id, "status", "done")
    assert discovery.is_done()


def test_estimates_roll_up(plan):
    assert plan.task(ids(plan, "Discovery")).rolled_up_estimate() == 4
    assert plan.root.rolled_up_estimate() == 9


def test_unestimated_leaves_are_counted_not_hidden(plan):
    """A roll-up that treats unestimated work as zero understates the plan; the count is
    what lets a view say so."""
    plan.add_task(ids(plan, "Build"), Task(title="Unknown work"))
    assert plan.root.unestimated() == 1


def test_dependencies_are_stored_on_the_waiting_task(plan):
    write_up, build = ids(plan, "Write-up"), ids(plan, "Build")
    plan.set_dependencies(build, [write_up])
    assert plan.task(build).depends_on == [write_up]


def test_blockers_are_the_dependencies_that_are_not_done(plan):
    write_up, build = ids(plan, "Write-up"), ids(plan, "Build")
    plan.set_dependencies(build, [write_up])
    assert [task.title for task in plan.blockers(build)] == ["Write-up"]
    plan.set_field(write_up, "status", "done")
    assert plan.blockers(build) == []


def test_a_task_cannot_depend_on_itself(plan):
    build = ids(plan, "Build")
    with pytest.raises(ValueError, match="cannot depend on itself"):
        plan.set_dependencies(build, [build])


def test_a_dependency_must_exist(plan):
    with pytest.raises(ValueError, match="no such task"):
        plan.set_dependencies(ids(plan, "Build"), ["nope"])


def test_a_dependency_cycle_is_refused(plan):
    """Caught here so the plan is never unsatisfiable — a scheduler above never has to."""
    write_up, build = ids(plan, "Write-up"), ids(plan, "Build")
    plan.set_dependencies(build, [write_up])
    with pytest.raises(ValueError, match="cycle"):
        plan.set_dependencies(write_up, [build])


def test_a_longer_cycle_is_refused_too(plan):
    a, b, c = ids(plan, "Interviews"), ids(plan, "Write-up"), ids(plan, "Build")
    plan.set_dependencies(b, [a])
    plan.set_dependencies(c, [b])
    with pytest.raises(ValueError, match="cycle"):
        plan.set_dependencies(a, [c])


def test_duplicate_dependencies_collapse(plan):
    write_up, build = ids(plan, "Write-up"), ids(plan, "Build")
    plan.set_dependencies(build, [write_up, write_up])
    assert plan.task(build).depends_on == [write_up]


def test_deleting_a_task_leaves_dependencies_on_it_alone(plan):
    """Undo has to restore the plan exactly, so delete must not rewrite other tasks."""
    write_up, build = ids(plan, "Write-up"), ids(plan, "Build")
    plan.set_dependencies(build, [write_up])
    plan.remove_task(write_up)
    assert plan.task(build).depends_on == [write_up]
    assert plan.blockers(build) == []  # But it no longer blocks: it cannot be resolved.


# -- structure ---------------------------------------------------------------------------------


def test_a_stale_text_edit_is_refused(plan):
    task_id = ids(plan, "Build")
    plan.set_description(task_id, "hello")
    with pytest.raises(ValueError, match="stale TextEdit"):
        plan.apply_text_edit(TextEdit(task_id, 0, "goodbye", "x"))


def test_removing_and_restoring_returns_the_subtree(plan):
    discovery = plan.task(ids(plan, "Discovery"))
    child_id = discovery.children[0].id
    parent_id, index = plan.remove_task(discovery.id)
    assert not plan.has(child_id)
    plan.restore_task(parent_id, discovery, index)
    assert plan.has(child_id)
    assert plan.root.children[0] is discovery


def test_a_cross_parent_move_announces_both_parents(plan):
    seen: list[str] = []
    plan.structure_changed.connect(seen.append)
    build, discovery = ids(plan, "Build"), ids(plan, "Discovery")
    plan.move_task(build, discovery, 0)
    assert seen == [plan.root.id, discovery]


def test_a_task_cannot_be_moved_inside_itself(plan):
    discovery = plan.task(ids(plan, "Discovery"))
    with pytest.raises(ValueError, match="inside itself"):
        plan.move_task(discovery.id, discovery.children[0].id, 0)


def test_the_root_is_not_removable(plan):
    with pytest.raises(ValueError, match="root"):
        plan.remove_task(plan.root.id)


def test_folder_names_avoid_siblings_and_reserved_names():
    assert unique_folder_name("First Slice", set()) == "first-slice"
    assert unique_folder_name("First Slice", {"first-slice"}) == "first-slice-2"
    assert unique_folder_name("modules", {"modules"}) == "modules-2"


def test_folder_names_transliterate_rather_than_strip():
    assert unique_folder_name("Møte på Sørøya", set()) == "mote-pa-soroya"
