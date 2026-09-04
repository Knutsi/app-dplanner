"""The library model: its index, its graph invariants, and its prose."""

import pytest

from dplanner.domain.model import EDGE_KINDS, Library, Project, Step, TextEdit


@pytest.fixture
def library():
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in ("Read the spec", "Draft the model", "Review"):
        library.add_child(project.id, Step(title=title))
    return library


def find(library, title):
    return next(node for node in library.nodes() if getattr(node, "title", None) == title)


# -- the index ---------------------------------------------------------------------------------


def test_one_index_spans_all_three_kinds(library):
    """`Repository.owner(id)` is flat over ids, so every level must answer to the same
    lookup — the framework does not know this model has levels."""
    project = find(library, "Discovery")
    step = find(library, "Review")
    assert library.has(library.id) and library.has(project.id) and library.has(step.id)
    assert library.node(step.id) is step
    assert [node.kind for node in library.nodes()][:2] == ["project", "step"]


def test_the_root_is_indexed_but_never_iterated(library):
    """The library root has no directory and can carry no module data, so nothing
    downstream — the migration pass, the flush — may ever see it in `nodes()`."""
    assert library.has(library.id)
    assert library.id not in {node.id for node in library.nodes()}


def test_a_step_knows_which_project_it_is_in(library):
    step = find(library, "Review")
    assert library.project_of(step.id).title == "Discovery"
    assert library.parent_of(library.id) is None


def test_a_change_belongs_to_the_project_it_is_in(library):
    """What a view of one project asks before redrawing for a signal naming any node."""
    project = find(library, "Discovery")
    step = find(library, "Review")
    other = Project(title="Other")
    library.add_child(library.id, other)
    assert library.belongs_to(step.id, project.id)
    assert library.belongs_to(project.id, project.id)  # The project's own fields count.
    assert not library.belongs_to(step.id, other.id)
    assert not library.belongs_to(other.id, project.id)
    assert not library.belongs_to("gone", project.id)  # A removed step is nobody's.


def test_asking_for_the_wrong_kind_is_an_error(library):

    project = find(library, "Discovery")
    with pytest.raises(KeyError):
        library.step(project.id)


# -- fields ------------------------------------------------------------------------------------


def test_each_kind_has_its_own_editable_fields(library):
    project = find(library, "Discovery")
    step = find(library, "Review")
    library.set_field(project.id, "summary", "what we do not know yet")
    library.set_field(step.id, "title", "Review everything")
    assert project.summary == "what we do not know yet"
    assert step.title == "Review everything"


def test_a_field_the_kind_does_not_have_is_refused(library):
    step = find(library, "Review")
    with pytest.raises(ValueError, match="not an editable field of a step"):
        library.set_field(step.id, "summary", "nope")


def test_setting_a_field_to_what_it_already_is_emits_nothing(library):
    project = find(library, "Discovery")
    seen = []
    library.field_changed.connect(lambda *args: seen.append(args))
    library.set_field(project.id, "title", "Discovery")
    assert seen == []


def test_the_origin_reaches_the_signal(library):
    """A view passes itself and ignores its own echo; identity is the whole mechanism."""
    project = find(library, "Discovery")
    view = object()
    seen = []
    library.field_changed.connect(lambda node_id, field, origin: seen.append(origin))
    library.set_field(project.id, "title", "Discovery Phase", view)
    assert seen == [view]


# -- the graph ---------------------------------------------------------------------------------


def test_a_step_waits_on_another(library):
    first, second = find(library, "Read the spec"), find(library, "Draft the model")
    library.set_edges(second.id, "requires", [first.id])
    assert [step.title for step in library.requires(second.id)] == ["Read the spec"]
    assert [step.title for step in library.dependents(first.id)] == ["Draft the model"]


def test_a_step_cannot_wait_on_itself(library):
    step = find(library, "Review")
    with pytest.raises(ValueError, match="cannot depend on itself"):
        library.set_edges(step.id, "requires", [step.id])


def test_an_ordering_kind_refuses_a_cycle(library):
    first, second = find(library, "Read the spec"), find(library, "Draft the model")
    library.set_edges(second.id, "requires", [first.id])
    with pytest.raises(ValueError, match="that is a cycle"):
        library.set_edges(first.id, "requires", [second.id])


def test_a_non_ordering_kind_allows_one(library):
    """`relates` is a link, not an order, so two steps may point at each other."""
    first, second = find(library, "Read the spec"), find(library, "Draft the model")
    assert EDGE_KINDS["relates"] is False
    library.set_edges(second.id, "relates", [first.id])
    library.set_edges(first.id, "relates", [second.id])
    assert first.edges["relates"] == [second.id]


def test_the_refusal_is_asked_as_a_question_as_well_as_enforced(library):
    """A view dragging a link asks before the drop; set_edges asks before it writes. One
    implementation, so live feedback and the write can never disagree."""
    first, second = find(library, "Read the spec"), find(library, "Draft the model")
    assert library.link_refusal(second.id, "requires", first.id) is None
    library.set_edges(second.id, "requires", [first.id])

    refusal = library.link_refusal(first.id, "requires", second.id)
    assert refusal is not None and "that is a cycle" in refusal
    with pytest.raises(ValueError, match="that is a cycle"):
        library.set_edges(first.id, "requires", [second.id])


def test_an_unknown_kind_cannot_be_created(library):
    step = find(library, "Review")
    with pytest.raises(ValueError, match="is not an edge kind"):
        library.set_edges(step.id, "invented", [])


def test_an_edge_cannot_leave_its_project(library):
    other = Project(title="Build")
    library.add_child(library.id, other)
    outsider = Step(title="Ship it")
    library.add_child(other.id, outsider)
    with pytest.raises(ValueError, match="no such step"):
        library.set_edges(find(library, "Review").id, "requires", [outsider.id])


def test_clearing_an_edge_kind_removes_it_entirely(library):
    first, second = find(library, "Read the spec"), find(library, "Draft the model")
    library.set_edges(second.id, "requires", [first.id])
    library.set_edges(second.id, "requires", [])
    assert second.edges == {}


def test_deleting_a_step_leaves_the_edges_that_named_it(library):
    """Undo has to restore the graph exactly, so a delete never rewrites anyone else's
    edges. `requires()` skips what it cannot resolve instead."""
    first, second = find(library, "Read the spec"), find(library, "Draft the model")
    library.set_edges(second.id, "requires", [first.id])
    library.remove_child(first.id)
    assert second.edges["requires"] == [first.id]
    assert library.requires(second.id) == []


def test_boundary_edges_are_the_links_that_cross_a_set(library):
    """Both directions and both kinds count; links among the set stay out of it."""
    first, second, third = (
        find(library, "Read the spec"),
        find(library, "Draft the model"),
        find(library, "Review"),
    )
    library.set_edges(second.id, "requires", [first.id])
    library.set_edges(third.id, "requires", [second.id])
    library.set_edges(first.id, "relates", [third.id])
    assert library.boundary_edges([second.id]) == [
        (second.id, "requires", first.id),
        (third.id, "requires", second.id),
    ]
    assert library.boundary_edges([first.id, second.id]) == [
        (first.id, "relates", third.id),
        (third.id, "requires", second.id),
    ]
    assert library.boundary_edges([first.id, second.id, third.id]) == []


def test_boundary_edges_skip_a_link_to_a_step_that_is_gone(library):
    first, second = find(library, "Read the spec"), find(library, "Draft the model")
    library.set_edges(second.id, "requires", [first.id])
    library.remove_child(first.id)
    assert library.boundary_edges([second.id]) == []


def test_removing_edges_is_one_command_per_list_and_one_undo_step(library):
    from dplanner.domain.commands import remove_edges_command

    first, second, third = (
        find(library, "Read the spec"),
        find(library, "Draft the model"),
        find(library, "Review"),
    )
    library.set_edges(third.id, "requires", [first.id, second.id])
    library.set_edges(second.id, "relates", [first.id])
    command = remove_edges_command(
        library,
        [(third.id, "requires", first.id), (third.id, "requires", second.id)],
        "Isolate Step",
    )
    assert command.text() == "Isolate Step"
    assert len(command.commands) == 1  # One list, one replacement — not two fighting ones.
    command.redo(library)
    assert "requires" not in third.edges
    assert second.edges["relates"] == [first.id]
    command.undo(library)
    assert third.edges["requires"] == [first.id, second.id]


# -- prose -------------------------------------------------------------------------------------


def test_prose_is_keyed_by_the_module_that_owns_it(library):
    step = find(library, "Review")
    library.set_text(step.id, "step_description", "# Notes\n")
    assert library.text(step.id, "step_description") == "# Notes\n"
    assert library.text(step.id, "something_else") == ""


def test_a_positioned_edit_splices(library):
    step = find(library, "Review")
    library.set_text(step.id, "step_description", "hello")
    library.apply_text_edit(TextEdit(step.id, "step_description", 5, "", " there"))
    assert library.text(step.id, "step_description") == "hello there"


def test_a_stale_edit_is_refused(library):
    """A binding whose view has drifted would otherwise write plausible nonsense."""
    step = find(library, "Review")
    library.set_text(step.id, "step_description", "hello")
    with pytest.raises(ValueError, match="stale TextEdit"):
        library.apply_text_edit(TextEdit(step.id, "step_description", 0, "HELLO", "x"))


def test_emptying_a_document_removes_it(library):
    step = find(library, "Review")
    library.set_text(step.id, "step_description", "hello")
    library.set_text(step.id, "step_description", "")
    assert "step_description" not in step.module_text


# -- structure ---------------------------------------------------------------------------------


def test_folder_names_are_unique_among_siblings(library):
    project = find(library, "Discovery")
    library.add_child(project.id, Step(title="Review"))
    assert [step.folder_name for step in project.steps][-2:] == ["review", "review-2"]


def test_a_folder_name_does_not_follow_a_retitle(library):
    step = find(library, "Review")
    library.set_field(step.id, "title", "Review everything")
    assert step.folder_name == "review"


def test_remove_reports_where_it_was_so_undo_can_restore_it(library):
    project = find(library, "Discovery")
    step = find(library, "Draft the model")
    parent_id, index = library.remove_child(step.id)
    assert (parent_id, index) == (project.id, 1)
    library.restore_child(parent_id, step, index)
    assert [s.title for s in project.steps][1] == "Draft the model"


def test_a_project_cannot_hold_a_project(library):
    with pytest.raises(ValueError, match="does not hold"):
        library.add_child(find(library, "Discovery").id, Project(title="Nested"))


def test_the_library_itself_cannot_be_removed(library):
    with pytest.raises(ValueError, match="the library itself cannot be removed"):
        library.remove_child(library.id)


# -- module data -------------------------------------------------------------------------------


def test_module_data_carries_the_origin_that_caused_it(library):
    """An aspect editor is a view of this data; without an origin it would hear its own
    echo and reload the field the user is still typing in."""
    view = object()
    seen = []
    library.module_data_changed.connect(lambda node_id, module_id, origin: seen.append(origin))
    step = find(library, "Review")
    library.set_module_data(step.id, "step_estimation", {"days": 3.0}, view)
    assert seen == [view]


def test_an_empty_entry_removes_itself(library):
    step = find(library, "Review")
    library.set_module_data(step.id, "step_estimation", {"days": 3.0})
    assert step.module_data["step_estimation"] == {"days": 3.0}
    library.set_module_data(step.id, "step_estimation", {})
    assert "step_estimation" not in step.module_data


def test_undoing_module_data_carries_a_token_matching_no_view(library):
    """So every view applies an undo, including the one that made the original edit."""
    from dplanner.domain.commands import UNDO_ORIGIN, SetModuleDataCommand

    step = find(library, "Review")
    seen = []
    library.module_data_changed.connect(lambda _node, _module, origin: seen.append(origin))
    view = object()
    command = SetModuleDataCommand(step.id, "step_estimation", {"days": 3.0}, view_origin=view)
    command.redo(library)
    command.undo(library)
    assert seen == [view, UNDO_ORIGIN]


def test_a_command_label_names_the_change_rather_than_the_mechanism(library):
    from dplanner.domain.commands import SetModuleDataCommand

    step = find(library, "Review")
    assert SetModuleDataCommand(step.id, "m", {"x": 1}, label="Move Step").text() == "Move Step"
    assert SetModuleDataCommand(step.id, "m", {"x": 1}).text() == "Edit"


def test_children_can_be_reordered_in_place(library):
    project = library.projects[0]
    order = [step.id for step in project.steps]
    heard = []
    library.structure_changed.connect(lambda parent, origin: heard.append((parent, origin)))

    library.reorder_children(project.id, order[::-1], origin="outside")

    assert [step.id for step in project.steps] == order[::-1]
    assert heard == [(project.id, "outside")]
    library.reorder_children(project.id, order[::-1])
    assert len(heard) == 1  # Already in that order: nothing happened.
    with pytest.raises(ValueError, match="exactly the current children"):
        library.reorder_children(project.id, order[:-1])
