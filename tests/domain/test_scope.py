"""What a step gathers, and where its cone stops.

No ``qapp`` fixture: like the ordering walk it wraps, this is a plain function over the
model. The collectors here are named by a marker in ``module_data`` because that is what
the real aspects use, but nothing in ``scope.py`` knows the key — the predicates are the
argument.
"""

from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import upstream
from dplanner.domain.scope import cone, gatherers


def build(*titles):
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in titles:
        library.add_child(project.id, Step(title=title))
    return library, project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def link(library, project, waiter, source):
    """``waiter`` waits on ``source``."""
    step = by_title(project, waiter)
    waiting = [*step.edges.get("requires", []), by_title(project, source).id]
    SetEdgesCommand(step.id, "requires", waiting).redo(library)


def mark(project, title, kind):
    by_title(project, title).module_data[kind] = {"on": True}


def carries(kind):
    return lambda step: bool(step.module_data.get(kind))


def titles(steps):
    return [step.title for step in steps]


# -- the untruncated case ------------------------------------------------------


def test_with_nothing_to_stop_it_the_cone_is_the_whole_upstream():
    library, project = build("A", "B", "C")
    link(library, project, "B", "A")
    link(library, project, "C", "B")
    found = cone(library, project, by_title(project, "C").id)
    assert titles(found.steps) == ["A", "B"]
    assert found.boundaries == ()
    assert titles(found.steps) == titles(upstream(library, project, by_title(project, "C").id))


def test_the_origin_is_never_part_of_what_it_gathers():
    library, project = build("A", "B")
    link(library, project, "B", "A")
    found = cone(library, project, by_title(project, "B").id)
    assert titles(found.steps) == ["A"]


def test_an_edge_out_of_the_project_is_ignored():
    library, project = build("A", "B")
    other = Project(title="Elsewhere")
    library.add_child(library.id, other)
    stranger = Step(title="Stranger")
    library.add_child(other.id, stranger)
    step = by_title(project, "B")
    # The model refuses a cross-project edge; a hand-edited file can still carry one.
    step.edges["requires"] = [by_title(project, "A").id, stranger.id]
    assert titles(cone(library, project, step.id).steps) == ["A"]


# -- stopping at a collector ---------------------------------------------------


def test_a_collector_gathers_only_what_is_behind_it_and_before_the_previous_one():
    library, project = build("Login", "Import", "Reporting", "Ship")
    for waiter, source in (("Import", "Login"), ("Reporting", "Import"), ("Ship", "Reporting")):
        link(library, project, waiter, source)
    mark(project, "Import", "feature")
    found = cone(library, project, by_title(project, "Ship").id, stops_at=carries("feature"))
    assert titles(found.steps) == ["Reporting"]
    assert titles(found.boundaries) == ["Import"]


def test_a_boundary_is_reported_rather_than_traversed():
    library, project = build("A", "B", "C")
    link(library, project, "B", "A")
    link(library, project, "C", "B")
    mark(project, "B", "feature")
    found = cone(library, project, by_title(project, "C").id, stops_at=carries("feature"))
    assert titles(found.steps) == []
    assert titles(found.boundaries) == ["B"]


def test_the_origin_is_not_stopped_by_its_own_marker():
    library, project = build("A", "B")
    link(library, project, "B", "A")
    mark(project, "B", "feature")
    found = cone(library, project, by_title(project, "B").id, stops_at=carries("feature"))
    assert titles(found.steps) == ["A"]


def test_a_step_reachable_around_a_boundary_is_still_gathered():
    library, project = build("Shared", "Gate", "Ship")
    link(library, project, "Gate", "Shared")
    link(library, project, "Ship", "Gate")
    link(library, project, "Ship", "Shared")
    mark(project, "Gate", "feature")
    found = cone(library, project, by_title(project, "Ship").id, stops_at=carries("feature"))
    assert titles(found.steps) == ["Shared"]
    assert titles(found.boundaries) == ["Gate"]


def test_a_milestone_stops_at_milestones_and_keeps_the_features_between():
    library, project = build("Work", "Import", "v1", "Reporting", "Export", "v2")
    for waiter, source in (
        ("Import", "Work"),
        ("v1", "Import"),
        ("Reporting", "v1"),
        ("Export", "Reporting"),
        ("v2", "Export"),
    ):
        link(library, project, waiter, source)
    for title in ("Import", "Export"):
        mark(project, title, "feature")
    for title in ("v1", "v2"):
        mark(project, title, "milestone")

    found = cone(library, project, by_title(project, "v2").id, stops_at=carries("milestone"))
    assert titles(found.steps) == ["Reporting", "Export"]
    assert titles(found.boundaries) == ["v1"]
    assert [step.title for step in found.steps if carries("feature")(step)] == ["Export"]


# -- the inversion -------------------------------------------------------------


def test_gatherers_names_the_feature_each_step_belongs_to():
    library, project = build("Work", "Import", "Reporting", "Export")
    for waiter, source in (
        ("Import", "Work"),
        ("Reporting", "Import"),
        ("Export", "Reporting"),
    ):
        link(library, project, waiter, source)
    for title in ("Import", "Export"):
        mark(project, title, "feature")

    owners = gatherers(library, project, carried_by=carries("feature"), stops_at=carries("feature"))
    named = {
        by_title(project, title).title: tuple(
            project.step(owner).title for owner in owners.get(by_title(project, title).id, ())
        )
        for title in ("Work", "Import", "Reporting", "Export")
    }
    assert named == {
        "Work": ("Import",),
        "Import": ("Import",),
        "Reporting": ("Export",),
        "Export": ("Export",),
    }


def test_a_step_feeding_two_features_is_gathered_by_both():
    library, project = build("Shared", "One", "Two")
    link(library, project, "One", "Shared")
    link(library, project, "Two", "Shared")
    for title in ("One", "Two"):
        mark(project, title, "feature")
    owners = gatherers(library, project, carried_by=carries("feature"), stops_at=carries("feature"))
    shared = owners[by_title(project, "Shared").id]
    assert [project.step(owner).title for owner in shared] == ["One", "Two"]


def test_a_step_no_collector_reaches_is_absent_rather_than_empty():
    library, project = build("Orphan", "Import")
    mark(project, "Import", "feature")
    owners = gatherers(library, project, carried_by=carries("feature"), stops_at=carries("feature"))
    assert by_title(project, "Orphan").id not in owners


# -- defensive -----------------------------------------------------------------


def test_a_hand_edited_cycle_terminates():
    library, project = build("A", "B")
    first, second = by_title(project, "A"), by_title(project, "B")
    first.edges["requires"] = [second.id]  # The model would refuse this; a file need not.
    second.edges["requires"] = [first.id]
    assert titles(cone(library, project, first.id).steps) == ["A", "B"]
