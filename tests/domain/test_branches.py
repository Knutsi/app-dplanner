"""Which steps are on a feature branch, derived from the links.

No ``qapp`` fixture: a plain walk over the model. A cut and a landing are named here by a
key in ``module_data`` of the test's own choosing, because nothing in ``branches.py`` knows
where the real aspects keep them — the readers are the argument.
"""

from dplanner.domain import branches
from dplanner.domain.commands import SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.ordering import downstream, left_between


def build(*titles):
    library = Library()
    project = Project(title="Discovery")
    library.add_child(library.id, project)
    for title in titles:
        library.add_child(project.id, Step(title=title))
    return library, project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def link(library, project, waiter, *sources):
    """``waiter`` waits on each of ``sources``."""
    step = by_title(project, waiter)
    waiting = [*step.edges.get("requires", []), *(by_title(project, s).id for s in sources)]
    SetEdgesCommand(step.id, "requires", waiting).redo(library)


def unlink(library, project, waiter, source):
    step = by_title(project, waiter)
    kept = [i for i in step.edges["requires"] if i != by_title(project, source).id]
    SetEdgesCommand(step.id, "requires", kept).redo(library)


def cut(project, title, branch):
    by_title(project, title).module_data["cut"] = {"branch": branch}


def land(project, title, cut_title):
    by_title(project, title).module_data["land"] = {"cut": by_title(project, cut_title).id}


def reading(project, done=()):
    return branches.read(
        project,
        branch_of=lambda step: step.module_data.get("cut", {}).get("branch", ""),
        cut_of=lambda step: step.module_data.get("land", {}).get("cut"),
        is_done=lambda step: step.title in done,
    )


def titles(steps):
    return [step.title for step in steps]


def stacks_plan():
    """The exploration's plan: main work, then a cut, a fan-out and back in, a landing."""
    library, project = build("F8", "F9", "B22", "S16", "S17", "S18", "F19", "S27", "R28", "M21")
    link(library, project, "F9", "F8")
    link(library, project, "B22", "F8")
    link(library, project, "S16", "B22")
    link(library, project, "S17", "S16")
    link(library, project, "S18", "S16")
    link(library, project, "F19", "S17", "S18")
    link(library, project, "S27", "F19")
    link(library, project, "R28", "S27")
    link(library, project, "M21", "R28", "F9")
    cut(project, "B22", "feature/stacks")
    land(project, "S27", "B22")
    return library, project


# -- the walks the reading stands on ------------------------------------------------------------


def test_downstream_is_upstream_walked_the_other_way():
    _library, project = stacks_plan()
    assert titles(downstream(project, by_title(project, "S17").id)) == ["F19", "S27", "R28", "M21"]
    assert downstream(project, by_title(project, "M21").id) == []


def test_downstream_survives_a_cycle_a_hand_edit_made():
    library, project = build("A", "B")
    link(library, project, "B", "A")
    by_title(project, "A").edges["requires"] = [by_title(project, "B").id]
    assert titles(downstream(project, by_title(project, "A").id)) == ["B"]


def test_a_step_left_between_the_picked_ones_is_named():
    _library, project = stacks_plan()
    picked = {by_title(project, t).id for t in ("S16", "F19")}
    between = left_between(project, picked)
    assert between is not None and between.title in {"S17", "S18"}
    picked |= {by_title(project, t).id for t in ("S17", "S18")}
    assert left_between(project, picked) is None


# -- what is on the branch ----------------------------------------------------------------------


def test_everything_after_the_cut_until_the_landing_is_on_the_branch():
    _library, project = stacks_plan()
    (stretch,) = reading(project).stretches
    assert stretch.branch == "feature/stacks"
    assert titles(stretch.members) == ["S16", "S17", "S18", "F19"]
    assert not stretch.landed


def test_main_work_the_landing_waits_on_stays_on_main():
    library, project = stacks_plan()
    link(library, project, "S27", "F9")  # The landing needs the home page too.
    (stretch,) = reading(project).stretches
    assert "F9" not in titles(stretch.members)
    assert branches.late_entries(library, project, stretch) == []


def test_a_step_that_builds_on_the_branch_is_on_it_and_named_unlanded():
    library, project = stacks_plan()
    extra = Step(title="S41")
    library.add_child(project.id, extra)
    link(library, project, "S41", "S17")
    (stretch,) = reading(project).stretches
    assert "S41" in titles(stretch.members)
    assert titles(branches.unlanded(library, project, stretch)) == ["S41"]
    link(library, project, "S27", "S41")
    (stretch,) = reading(project).stretches
    assert branches.unlanded(library, project, stretch) == []


def test_main_work_linked_into_the_middle_is_a_late_entry():
    """The branch was cut before F9 landed on main, so S17's worktree will not have it."""
    library, project = stacks_plan()
    link(library, project, "S17", "F9")
    (stretch,) = reading(project).stretches
    entries = branches.late_entries(library, project, stretch)
    assert [(m.title, s.title) for m, s in entries] == [("S17", "F9")]
    link(library, project, "B22", "F9")  # Cut after it instead.
    (stretch,) = reading(project).stretches
    assert branches.late_entries(library, project, stretch) == []


def test_membership_follows_a_relink():
    library, project = stacks_plan()
    unlink(library, project, "S18", "S16")
    link(library, project, "S18", "F8")
    (stretch,) = reading(project).stretches
    assert "S18" not in titles(stretch.members)


# -- pairing -----------------------------------------------------------------------------------


def test_a_landing_pairs_only_while_its_cut_is_upstream():
    library, project = stacks_plan()
    unlink(library, project, "S16", "B22")
    found = reading(project)
    assert found.stretches == ()
    assert titles(found.stray_cuts) == ["B22"] and titles(found.stray_lands) == ["S27"]


def test_a_cut_two_landings_name_pairs_with_the_first():
    _library, project = stacks_plan()
    land(project, "R28", "B22")
    found = reading(project)
    assert [s.land.title for s in found.stretches] == ["S27"]
    assert titles(found.stray_lands) == ["R28"]


def test_a_landing_naming_no_cut_is_a_stray():
    _library, project = stacks_plan()
    by_title(project, "B22").module_data.pop("cut")
    found = reading(project)
    assert found.stretches == () and titles(found.stray_lands) == ["S27"]


# -- nesting, overlap and landing ------------------------------------------------------------


def nested_plan():
    """feature/stacks holds feature/undo: B29 cuts from it, S31 lands back into it."""
    library, project = build("F8", "B22", "S16", "B29", "S30", "S31", "F19", "S27", "M21")
    for waiter, source in (
        ("B22", "F8"),
        ("S16", "B22"),
        ("B29", "S16"),
        ("S30", "B29"),
        ("S31", "S30"),
        ("F19", "S31"),
        ("S27", "F19"),
        ("M21", "S27"),
    ):
        link(library, project, waiter, source)
    cut(project, "B22", "feature/stacks")
    land(project, "S27", "B22")
    cut(project, "B29", "feature/undo")
    land(project, "S31", "B29")
    return library, project


def test_a_branch_off_a_branch_is_based_on_it():
    _library, project = nested_plan()
    found = reading(project)
    outer, inner = (found.of_cut(by_title(project, t).id) for t in ("B22", "B29"))
    assert inner.inside(outer) and not outer.inside(inner)
    s30 = by_title(project, "S30").id
    assert found.innermost(s30) is inner
    assert found.base_of(s30, "main") == "feature/undo"
    assert found.base_of(by_title(project, "B29").id, "main") == "feature/stacks"
    assert found.base_of(by_title(project, "S31").id, "main") == "feature/stacks"
    assert found.base_of(by_title(project, "S27").id, "main") == "main"
    assert found.base_of(by_title(project, "F8").id, "main") == "main"


def test_a_landed_branch_hands_its_steps_back_to_the_one_it_was_cut_from():
    _library, project = nested_plan()
    found = reading(project, done={"S31"})
    assert found.base_of(by_title(project, "S30").id, "main") == "feature/stacks"
    found = reading(project, done={"S31", "S27"})
    assert found.base_of(by_title(project, "S30").id, "main") == "main"


def test_two_stretches_crossing_without_nesting_overlap():
    library, project = build("B1", "B2", "A", "L1", "L2")
    link(library, project, "A", "B1", "B2")
    link(library, project, "L1", "A")
    link(library, project, "L2", "A")
    cut(project, "B1", "one")
    cut(project, "B2", "two")
    land(project, "L1", "B1")
    land(project, "L2", "B2")
    found = reading(project)
    a = by_title(project, "A").id
    assert len(found.holding(a)) == 2 and found.overlaps(a)
    assert found.innermost(a) is None
