"""A tab of one project is not rebuilt by a change in another, and says while it owes one.

Every project-scoped view hears the model through ``follow_project``, so the property is
asserted once per surface here rather than trusted per module. A rebuild is counted through
the class's own refresh method, patched before the tab is built so the bound method the
subscription holds is the counted one. The same table's second half is *Signalling*: every
debounced view carries an ``UpdatingIndicator`` over the settle it would otherwise spend
showing a stale picture in silence.
"""

from operator import attrgetter

import pytest

from dplanner.domain.commands import AddNodeCommand, SetFieldCommand
from dplanner.domain.model import Step
from dplanner.modules.coverage.activity import COVERAGE_KIND
from dplanner.modules.docs.activity import DOCS_KIND, DocsActivity
from dplanner.modules.notes.activity import NOTES_KIND
from dplanner.modules.progression.module import PROGRESSION_KIND, ProgressionActivity
from dplanner.modules.project_assets.activity import ASSETS_KIND, AssetsActivity
from dplanner.modules.project_editor.module import PROJECT_KIND, ProjectActivity
from dplanner.modules.step_order.module import ORDER_KIND, OrderActivity

# The module rather than the class: a name starting with "Test" bound here would be collected.
from dplanner.modules.testing import activity as testing
from dplanner.modules.time_estimates.module import TIME_KIND, TimeEstimatesActivity

VIEWS = [
    pytest.param(PROJECT_KIND, ProjectActivity, "_sync", id="canvas"),
    pytest.param(ORDER_KIND, OrderActivity, "_refresh", id="order"),
    pytest.param(TIME_KIND, TimeEstimatesActivity, "_refresh", id="time"),
    pytest.param(PROGRESSION_KIND, ProgressionActivity, "_refresh", id="progression"),
    pytest.param(testing.TESTS_KIND, testing.TestsActivity, "_refresh", id="tests"),
    pytest.param(DOCS_KIND, DocsActivity, "_refresh", id="docs"),
    pytest.param(ASSETS_KIND, AssetsActivity, "_refresh", id="assets"),
]

# Where each view keeps its indicator, from the activity the tab host hands back. The canvas
# has none: it settles once per event-loop turn, not over the 300-500 ms a person can read.
INDICATORS = [
    pytest.param(ORDER_KIND, "updating", id="order"),
    pytest.param(TIME_KIND, "updating", id="time"),
    pytest.param(PROGRESSION_KIND, "updating", id="progression"),
    pytest.param(testing.TESTS_KIND, "updating", id="tests"),
    pytest.param(DOCS_KIND, "page.updating", id="docs"),
    pytest.param(ASSETS_KIND, "updating", id="assets"),
    pytest.param(COVERAGE_KIND, "updating", id="coverage"),
    pytest.param(NOTES_KIND, "view.updating", id="notes"),
]


@pytest.fixture
def two_projects(services, make_project):
    library = services.document
    mine, other = make_project("Mine"), make_project("Other")
    for project in (mine, other):
        AddNodeCommand(project.id, Step(title="Work")).redo(library)
    return mine, other


@pytest.mark.parametrize(("kind", "activity_type", "method"), VIEWS)
def test_a_change_in_another_project_does_not_rebuild_the_tab(
    services, two_projects, monkeypatch, kind, activity_type, method
):
    mine, other = two_projects
    rebuilds = []
    original = getattr(activity_type, method)

    def counted(self, *args, **kwargs):
        rebuilds.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(activity_type, method, counted)
    services.tabs.open(kind, mine.id)
    before = len(rebuilds)

    services.undo.push(SetFieldCommand(other.steps[0].id, "title", "Renamed elsewhere"))
    assert len(rebuilds) == before
    services.undo.push(SetFieldCommand(mine.steps[0].id, "title", "Renamed here"))
    assert len(rebuilds) == before + 1


@pytest.mark.parametrize(("kind", "activity_type", "method"), VIEWS)
def test_a_burst_of_edits_rebuilds_the_tab_once(
    services, two_projects, monkeypatch, kind, activity_type, method
):
    """With immediate mode off — the window's regime — a run of pushes is one rebuild,
    after the quiet spell or when the service settles it, never one per keystroke."""
    mine, _other = two_projects
    rebuilds = []
    original = getattr(activity_type, method)

    def counted(self, *args, **kwargs):
        rebuilds.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(activity_type, method, counted)
    services.debounce.set_immediate(False)
    services.tabs.open(kind, mine.id)
    before = len(rebuilds)  # Built once, synchronously.
    for title in ("one", "two", "three"):
        services.undo.push(SetFieldCommand(mine.steps[0].id, "title", title))
    assert len(rebuilds) == before  # Pending, not run.
    services.debounce.flush_all()
    assert len(rebuilds) == before + 1


@pytest.mark.parametrize(("kind", "where"), INDICATORS)
def test_the_strip_says_updating_from_the_change_until_the_view_has_rebuilt(
    services, two_projects, kind, where
):
    """DESIGN.md's *Signalling*: the content stays and the strip says a rebuild is owed.

    Immediate mode off, because that is the window's regime — in a test's own immediate mode
    the indicator is up and down inside the one ``trigger()`` and there is nothing to see.
    """
    mine, _other = two_projects
    services.debounce.set_immediate(False)
    try:
        activity = services.tabs.open(kind, mine.id)
        indicator = attrgetter(where)(activity)
        assert indicator.isHidden()
        services.undo.push(SetFieldCommand(mine.steps[0].id, "title", "Renamed here"))
        assert not indicator.isHidden()
        services.debounce.flush_all()
        assert indicator.isHidden()
    finally:
        services.debounce.set_immediate(True)


@pytest.mark.parametrize(("kind", "where"), INDICATORS)
def test_the_indicator_keeps_its_room_so_the_strip_never_reflows(
    services, two_projects, kind, where
):
    mine, _other = two_projects
    activity = services.tabs.open(kind, mine.id)
    assert attrgetter(where)(activity).sizePolicy().retainSizeWhenHidden()
