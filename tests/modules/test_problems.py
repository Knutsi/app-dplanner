"""The Problems panel: the lint registry, said where a plan is fixed.

It is a *second presenter* of ``lint_checks()`` — the same list ``dplanner project lint``
runs — so these tests care about what the panel does with a finding, not about what a
finding is: that is ``tests/cli``'s.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetFieldCommand
from dplanner.domain.model import Step
from dplanner.modules.problems.panel import NOTHING_WRONG, ProblemsPanel


@pytest.fixture
def project(services, make_project):
    """Two steps linked, and one orphan — `graph.orphan` with nothing else to say."""
    project = make_project("Discovery")
    first, second, orphan = Step(title="First"), Step(title="Second"), Step(title="Orphan")
    for step in (first, second, orphan):
        AddNodeCommand(project.id, step).redo(services.document)
    SetEdgesCommand(second.id, "requires", [first.id]).redo(services.document)
    return project


@pytest.fixture
def tab(services, project):
    return services.tabs.open("project", project.id)


def panel(tab) -> ProblemsPanel:
    content = tab._side_panel.frame.content
    assert isinstance(content, ProblemsPanel)
    return content


def rows(view):
    return [view.list.item(row).text() for row in range(view.list.count())]


# -- what it shows ------------------------------------------------------------------------------


def test_the_panel_lists_what_lint_reports(tab, project):
    view = panel(tab)
    assert [row.check for row in view.findings()]
    assert "graph.orphan" in {row.check for row in view.findings()}
    assert "Orphan" in rows(view)
    # Sorted by check and then subject, so like sits with like.
    checks = [row.check for row in view.findings()]
    assert checks == sorted(checks)


def test_a_row_says_the_verb_that_closes_it(tab):
    from dplanner.framework.list_rows import DETAIL_ROLE, TRAILING_ROLE

    view = panel(tab)
    row = next(i for i, f in enumerate(view.findings()) if f.check == "graph.orphan")
    finding = view.findings()[row]
    item = view.list.item(row)
    assert item.text() == "Orphan"
    assert item.data(DETAIL_ROLE) == finding.message and "dplanner step link" in finding.message
    # The trailing note is the step's key, and the check id is in the tooltip.
    assert item.data(TRAILING_ROLE) == "S3"
    assert item.toolTip().startswith("graph.orphan")


def test_a_clean_plan_says_so_and_the_list_stands_down(services, make_project):
    """One line of words, no glyph: `EmptyState` and nothing else."""
    project = make_project("Clean")
    tab = services.tabs.open("project", project.id)
    view = panel(tab)
    # A project with no steps has no topology to read and no graph to be wrong about.
    assert view.findings() == () or all(row.check.startswith("repo.") for row in view.findings())
    if not view.findings():
        assert view.empty.label.text() == NOTHING_WRONG and view.list.isHidden()


def test_the_reading_is_the_count_and_the_strip_button_wears_it(tab):
    view = panel(tab)
    assert view.reading() == f"({len(view.findings())})"
    button = tab._side_panel.button
    assert button is not None and button.text() == view.reading()


def test_the_reading_follows_the_plan(services, tab, project):
    """A count read, never probed: the panel recomputes on its own settled rebuild and the
    button reads what it last said."""
    view, button = panel(tab), tab._side_panel.button
    before = len(view.findings())
    orphan = next(step for step in project.steps if step.title == "Orphan")
    SetEdgesCommand(orphan.id, "requires", [project.steps[0].id]).redo(services.document)
    assert len(view.findings()) == before - 1
    assert button.text() == view.reading()


# -- landing on one -----------------------------------------------------------------------------


def test_picking_a_row_selects_and_centres_its_step(services, tab, project):
    view = panel(tab)
    orphan = next(step for step in project.steps if step.title == "Orphan")
    row = next(i for i in range(view.list.count()) if view.list.item(i).text() == "Orphan")
    view.list.setCurrentRow(row)
    assert services.context.current().selected_entities("step") == [orphan.id]


def test_a_project_scoped_finding_has_no_step_to_land_on(services, tab, project):
    """`repo.unset` and friends name the project; the row simply does not travel."""
    from dplanner.modules.problems.panel import SUBJECT_ROLE

    view = panel(tab)
    for i in range(view.list.count()):
        subject = view.list.item(i).data(SUBJECT_ROLE)
        assert subject is None or services.document.has(subject)


# -- handing it to an agent ---------------------------------------------------------------------


def test_the_fix_face_counts_what_it_would_act_on(tab):
    view = panel(tab)
    count = len(view.findings())
    assert view.fix_button is not None
    assert view.fix_button.text() == f"Fix {count} Problem{'' if count == 1 else 's'}"
    assert view.fix_button.isEnabled()


def test_the_fix_menu_lists_the_profiles_and_launches_one(services, tab, monkeypatch):
    from dplanner.modules.step_agent_instruction.module import StepAgentInstructionModule

    agent = next(m for m in services.modules if isinstance(m, StepAgentInstructionModule))
    launched: list[tuple[str, int]] = []

    def record(_self, _project_id, problems, profile) -> bool:
        launched.append((profile, len(problems)))
        return True

    monkeypatch.setattr(StepAgentInstructionModule, "fix_problems", record)
    view = panel(tab)
    menu = view.fix_menu()
    assert menu is not None
    entries = [action.text() for action in menu.actions()]
    assert entries and entries[0].endswith("(default)")
    menu.actions()[0].trigger()
    assert launched and launched[0][1] == len(view.findings())
    assert agent is not None


def test_a_clean_plan_offers_nothing_to_fix(services, make_project):
    tab = services.tabs.open("project", make_project("Clean").id)
    view = panel(tab)
    button = view.fix_button
    assert button is not None
    if not view.findings():
        assert not button.isEnabled()
        assert button.text() == "Fix Problems"


# -- one reading, two readers --------------------------------------------------------------------


def findings_of(services):
    module = next(m for m in services.modules if type(m).__name__ == "ProblemsModule")
    return module.findings


def test_the_panel_and_the_canvas_read_one_settled_answer(services, project, tab, monkeypatch):
    """Lint is super-linear in the size of a plan, so it runs on a settle and never on a
    canvas sync. Both surfaces read the one reading rather than taking their own."""
    shared = findings_of(services)
    reads: list[str] = []
    real = shared._read

    def counted(project_id):
        reads.append(project_id)
        return real(project_id)

    monkeypatch.setattr(shared, "_read", counted)

    services.debounce.set_immediate(False)
    try:
        for title in ("one", "two", "three"):
            services.undo.push(SetFieldCommand(project.steps[0].id, "title", title))
        assert reads == []  # A burst of edits asks nothing of lint.
        services.debounce.flush_all()
    finally:
        services.debounce.set_immediate(True)
    assert reads == [project.id]  # One reading for the burst, for the one project shown.

    # And the canvas paints from it without asking again.
    before = len(reads)
    tab._sync()
    assert len(reads) == before


def test_a_step_a_finding_is_about_is_flagged_on_the_canvas(services, project, tab):
    """`flagged` is the canvas's whole knowledge of a problem: which steps, never which."""
    shared = findings_of(services)
    services.debounce.flush_all()
    orphan = next(step for step in project.steps if step.title == "Orphan")
    assert orphan.id in shared.flagged(project.id)
    tab._sync()
    assert tab._scene._nodes[orphan.id]._accent.flagged


def test_a_project_nobody_has_asked_about_costs_nothing(services, project):
    """The first ask answers nothing and arrives on the next settle — which is what keeps
    the first canvas sync of a big plan off the expensive path.

    Asserted with immediate mode off, because that is the window's regime: run immediate,
    the settle lands inside the ask and the first answer is already the real one.
    """
    shared = findings_of(services)
    shared._found.clear()
    services.debounce.set_immediate(False)
    try:
        assert shared.flagged(project.id) == frozenset()
        services.debounce.flush_all()
    finally:
        services.debounce.set_immediate(True)
    assert shared.flagged(project.id)
