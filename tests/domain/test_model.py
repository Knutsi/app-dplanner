"""The product model: its index, its graph invariants, and its prose."""

import pytest

from dplanner.domain.model import EDGE_KINDS, Product, Project, Step, TextEdit


@pytest.fixture
def product():
    product = Product(name="Widget")
    project = Project(title="Discovery")
    product.add_child(product.id, project)
    for title in ("Read the spec", "Draft the model", "Review"):
        product.add_child(project.id, Step(title=title))
    return product


def find(product, title):
    return next(node for node in product.nodes() if getattr(node, "title", None) == title)


# -- the index ---------------------------------------------------------------------------------


def test_one_index_spans_all_three_kinds(product):
    """`Repository.owner(id)` is flat over ids, so every level must answer to the same
    lookup — the framework does not know this model has levels."""
    project = find(product, "Discovery")
    step = find(product, "Review")
    assert product.has(product.id) and product.has(project.id) and product.has(step.id)
    assert product.node(step.id) is step
    assert [node.kind for node in product.nodes()][:3] == ["product", "project", "step"]


def test_a_step_knows_which_project_it_is_in(product):
    step = find(product, "Review")
    assert product.project_of(step.id).title == "Discovery"
    assert product.parent_of(product.id) is None


def test_asking_for_the_wrong_kind_is_an_error(product):
    project = find(product, "Discovery")
    with pytest.raises(KeyError):
        product.step(project.id)


# -- fields ------------------------------------------------------------------------------------


def test_each_kind_has_its_own_editable_fields(product):
    project = find(product, "Discovery")
    product.set_field(product.id, "repository", "git@example.com:widget.git")
    product.set_field(project.id, "summary", "what we do not know yet")
    assert product.repository.endswith("widget.git")
    assert project.summary == "what we do not know yet"


def test_a_field_the_kind_does_not_have_is_refused(product):
    step = find(product, "Review")
    with pytest.raises(ValueError, match="not an editable field of a step"):
        product.set_field(step.id, "summary", "nope")


def test_setting_a_field_to_what_it_already_is_emits_nothing(product):
    seen = []
    product.field_changed.connect(lambda *args: seen.append(args))
    product.set_field(product.id, "name", "Widget")
    assert seen == []


def test_the_origin_reaches_the_signal(product):
    """A view passes itself and ignores its own echo; identity is the whole mechanism."""
    view = object()
    seen = []
    product.field_changed.connect(lambda node_id, field, origin: seen.append(origin))
    product.set_field(product.id, "name", "Widget 2", view)
    assert seen == [view]


# -- the graph ---------------------------------------------------------------------------------


def test_a_step_waits_on_another(product):
    first, second = find(product, "Read the spec"), find(product, "Draft the model")
    product.set_edges(second.id, "requires", [first.id])
    assert [step.title for step in product.requires(second.id)] == ["Read the spec"]
    assert [step.title for step in product.dependents(first.id)] == ["Draft the model"]


def test_a_step_cannot_wait_on_itself(product):
    step = find(product, "Review")
    with pytest.raises(ValueError, match="cannot depend on itself"):
        product.set_edges(step.id, "requires", [step.id])


def test_an_ordering_kind_refuses_a_cycle(product):
    first, second = find(product, "Read the spec"), find(product, "Draft the model")
    product.set_edges(second.id, "requires", [first.id])
    with pytest.raises(ValueError, match="that is a cycle"):
        product.set_edges(first.id, "requires", [second.id])


def test_a_non_ordering_kind_allows_one(product):
    """`relates` is a link, not an order, so two steps may point at each other."""
    first, second = find(product, "Read the spec"), find(product, "Draft the model")
    assert EDGE_KINDS["relates"] is False
    product.set_edges(second.id, "relates", [first.id])
    product.set_edges(first.id, "relates", [second.id])
    assert first.edges["relates"] == [second.id]


def test_the_refusal_is_asked_as_a_question_as_well_as_enforced(product):
    """A view dragging a link asks before the drop; set_edges asks before it writes. One
    implementation, so live feedback and the write can never disagree."""
    first, second = find(product, "Read the spec"), find(product, "Draft the model")
    assert product.link_refusal(second.id, "requires", first.id) is None
    product.set_edges(second.id, "requires", [first.id])

    refusal = product.link_refusal(first.id, "requires", second.id)
    assert refusal is not None and "that is a cycle" in refusal
    with pytest.raises(ValueError, match="that is a cycle"):
        product.set_edges(first.id, "requires", [second.id])


def test_an_unknown_kind_cannot_be_created(product):
    step = find(product, "Review")
    with pytest.raises(ValueError, match="is not an edge kind"):
        product.set_edges(step.id, "invented", [])


def test_an_edge_cannot_leave_its_project(product):
    other = Project(title="Build")
    product.add_child(product.id, other)
    outsider = Step(title="Ship it")
    product.add_child(other.id, outsider)
    with pytest.raises(ValueError, match="no such step"):
        product.set_edges(find(product, "Review").id, "requires", [outsider.id])


def test_clearing_an_edge_kind_removes_it_entirely(product):
    first, second = find(product, "Read the spec"), find(product, "Draft the model")
    product.set_edges(second.id, "requires", [first.id])
    product.set_edges(second.id, "requires", [])
    assert second.edges == {}


def test_deleting_a_step_leaves_the_edges_that_named_it(product):
    """Undo has to restore the graph exactly, so a delete never rewrites anyone else's
    edges. `requires()` skips what it cannot resolve instead."""
    first, second = find(product, "Read the spec"), find(product, "Draft the model")
    product.set_edges(second.id, "requires", [first.id])
    product.remove_child(first.id)
    assert second.edges["requires"] == [first.id]
    assert product.requires(second.id) == []


# -- prose -------------------------------------------------------------------------------------


def test_prose_is_keyed_by_the_module_that_owns_it(product):
    step = find(product, "Review")
    product.set_text(step.id, "step_description", "# Notes\n")
    assert product.text(step.id, "step_description") == "# Notes\n"
    assert product.text(step.id, "something_else") == ""


def test_a_positioned_edit_splices(product):
    step = find(product, "Review")
    product.set_text(step.id, "step_description", "hello")
    product.apply_text_edit(TextEdit(step.id, "step_description", 5, "", " there"))
    assert product.text(step.id, "step_description") == "hello there"


def test_a_stale_edit_is_refused(product):
    """A binding whose view has drifted would otherwise write plausible nonsense."""
    step = find(product, "Review")
    product.set_text(step.id, "step_description", "hello")
    with pytest.raises(ValueError, match="stale TextEdit"):
        product.apply_text_edit(TextEdit(step.id, "step_description", 0, "HELLO", "x"))


def test_emptying_a_document_removes_it(product):
    step = find(product, "Review")
    product.set_text(step.id, "step_description", "hello")
    product.set_text(step.id, "step_description", "")
    assert "step_description" not in step.module_text


# -- structure ---------------------------------------------------------------------------------


def test_folder_names_are_unique_among_siblings(product):
    project = find(product, "Discovery")
    product.add_child(project.id, Step(title="Review"))
    assert [step.folder_name for step in project.steps][-2:] == ["review", "review-2"]


def test_a_folder_name_does_not_follow_a_retitle(product):
    step = find(product, "Review")
    product.set_field(step.id, "title", "Review everything")
    assert step.folder_name == "review"


def test_remove_reports_where_it_was_so_undo_can_restore_it(product):
    project = find(product, "Discovery")
    step = find(product, "Draft the model")
    parent_id, index = product.remove_child(step.id)
    assert (parent_id, index) == (project.id, 1)
    product.restore_child(parent_id, step, index)
    assert [s.title for s in project.steps][1] == "Draft the model"


def test_a_project_cannot_hold_a_project(product):
    with pytest.raises(ValueError, match="does not hold"):
        product.add_child(find(product, "Discovery").id, Project(title="Nested"))


def test_the_product_itself_cannot_be_removed(product):
    with pytest.raises(ValueError, match="cannot be removed"):
        product.remove_child(product.id)


# -- module data -------------------------------------------------------------------------------


def test_module_data_carries_the_origin_that_caused_it(product):
    """An aspect editor is a view of this data; without an origin it would hear its own
    echo and reload the field the user is still typing in."""
    view = object()
    seen = []
    product.module_data_changed.connect(lambda node_id, module_id, origin: seen.append(origin))
    step = find(product, "Review")
    product.set_module_data(step.id, "step_estimation", {"days": 3.0}, view)
    assert seen == [view]


def test_an_empty_entry_removes_itself(product):
    step = find(product, "Review")
    product.set_module_data(step.id, "step_estimation", {"days": 3.0})
    assert step.module_data["step_estimation"] == {"days": 3.0}
    product.set_module_data(step.id, "step_estimation", {})
    assert "step_estimation" not in step.module_data


def test_undoing_module_data_carries_a_token_matching_no_view(product):
    """So every view applies an undo, including the one that made the original edit."""
    from dplanner.domain.commands import UNDO_ORIGIN, SetModuleDataCommand

    step = find(product, "Review")
    seen = []
    product.module_data_changed.connect(lambda _node, _module, origin: seen.append(origin))
    view = object()
    command = SetModuleDataCommand(step.id, "step_estimation", {"days": 3.0}, view_origin=view)
    command.redo(product)
    command.undo(product)
    assert seen == [view, UNDO_ORIGIN]


def test_a_command_label_names_the_change_rather_than_the_mechanism(product):
    from dplanner.domain.commands import SetModuleDataCommand

    step = find(product, "Review")
    assert SetModuleDataCommand(step.id, "m", {"x": 1}, label="Move Step").text() == "Move Step"
    assert SetModuleDataCommand(step.id, "m", {"x": 1}).text() == "Edit"
