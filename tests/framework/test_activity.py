"""What a view of one project hears: ``follow_project`` and ``follow_target``.

Qt-free on purpose — the helpers are plain functions over the model's core signals, and
the property they own (a change elsewhere in the library is not this view's to redraw
for) is asserted here once rather than re-derived in every tab's tests.
"""

from dplanner.domain.model import Library, Project, Step, TextEdit
from dplanner.framework.activity import follow_project, follow_target


def build():
    library = Library()
    projects = []
    for name in ("Alpha", "Beta"):
        project = Project(title=name)
        library.add_child(library.id, project)
        for title in ("one", "two"):
            library.add_child(project.id, Step(title=title))
        projects.append(project)
    return library, projects[0], projects[1]


def test_only_changes_inside_the_project_are_heard():
    library, alpha, beta = build()
    heard = []
    follow_project(library, alpha.id, lambda: heard.append(True))

    library.set_field(beta.steps[0].id, "title", "Renamed")
    assert heard == []

    library.set_field(alpha.steps[0].id, "title", "Renamed")
    library.set_field(alpha.id, "title", "Alpha!")  # The project's own fields count.
    library.apply_text_edit(TextEdit(alpha.steps[1].id, "notes", 0, "", "prose"))
    library.set_module_data(alpha.steps[0].id, "estimation", {"days": 1.0})
    library.set_edges(alpha.steps[1].id, "requires", [alpha.steps[0].id])
    library.add_child(alpha.id, Step(title="three"))
    assert len(heard) == 6

    library.add_child(beta.id, Step(title="three"))
    library.add_child(library.id, Project(title="Gamma"))  # Membership is no project's.
    assert len(heard) == 6


def test_unfollowing_stops_every_signal():
    library, alpha, _beta = build()
    heard = []
    unfollow = follow_project(library, alpha.id, lambda: heard.append(True))
    unfollow()
    library.set_field(alpha.steps[0].id, "title", "Renamed")
    library.apply_text_edit(TextEdit(alpha.steps[1].id, "notes", 0, "", "prose"))
    assert heard == []


def test_the_signals_that_count_can_be_chosen():
    library, alpha, _beta = build()
    heard = []
    follow_project(library, alpha.id, lambda: heard.append(True), signals=(library.field_changed,))
    library.apply_text_edit(TextEdit(alpha.steps[1].id, "notes", 0, "", "prose"))
    assert heard == []
    library.set_field(alpha.steps[0].id, "title", "Renamed")
    assert heard == [True]


def test_a_moving_target_is_asked_at_every_signal():
    library, alpha, beta = build()
    heard = []
    target = [alpha.steps[0].id]
    follow_target(library, lambda: target[0], lambda: heard.append(True))

    library.set_field(beta.steps[0].id, "title", "Renamed")
    assert heard == []
    library.set_field(alpha.steps[1].id, "title", "Renamed")  # A sibling of the target.
    assert len(heard) == 1

    target[0] = beta.id  # A project target stands for its own project.
    library.set_field(beta.steps[0].id, "title", "Again")
    assert len(heard) == 2

    target[0] = None  # Nothing on show hears nothing.
    library.set_field(alpha.steps[0].id, "title", "Again")
    target[0] = "gone"  # A removed step is nobody's.
    library.set_field(alpha.steps[0].id, "title", "Once more")
    assert len(heard) == 2
