"""The Coverage tab: lanes, cards and links over a real project; a pick lights a path
and scrolls the other lanes; a double-click opens the thing; the verbs that reach it."""

import pytest
from tests.modules.test_spec import imported

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.modules.coverage.activity import CoverageActivity
from dplanner.modules.coverage.module import NO_PASSAGE_REASON, NOT_TRACED_REASON
from dplanner.modules.coverage.scene import LANE_MIN_W, LaneItem
from dplanner.modules.coverage.trace import FEATURES, MILESTONES, OUTCOMES, SPEC
from dplanner.modules.feature.aspect import MODULE_ID as FEATURE_ID
from dplanner.modules.feature.aspect import FeatureSource
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.step_milestone.aspect import MODULE_ID as MILESTONE_ID
from dplanner.modules.step_milestone.aspect import write as write_milestone
from dplanner.modules.testing.aspect import MODULE_ID as TESTING_ID
from dplanner.modules.testing.aspect import Test, write

GUIDE = "# Guide\n\nOperators MUST import a CSV.\n\nEvery login is logged.\n\nNothing else.\n"


@pytest.fixture
def project(services, make_project):
    """work (tests) → Import (a feature) → Beta (milestone); Export a feature of its own."""
    project = make_project("Discovery")
    imported(services, project, "guide", GUIDE.encode(), "guide.md")
    library = services.document
    work, imp, beta = Step(title="work"), Step(title="Import"), Step(title="Beta")
    export = Step(title="Export")
    for step in (work, imp, beta, export):
        AddNodeCommand(project.id, step).redo(library)
    SetEdgesCommand(imp.id, "requires", [work.id]).redo(library)
    SetEdgesCommand(beta.id, "requires", [imp.id]).redo(library)
    tests = [Test(f"T{100 + n}", f"test {n}") for n in range(30)]  # Enough to overflow.
    library.set_module_data(work.id, TESTING_ID, write(tests))
    library.set_module_data(
        imp.id, FEATURE_ID, feature_write((FeatureSource("guide", "import a CSV"),))
    )
    library.set_module_data(
        export.id, FEATURE_ID, feature_write((FeatureSource("guide", "Every login is logged"),))
    )
    library.set_module_data(beta.id, MILESTONE_ID, write_milestone("M1"))
    return project


@pytest.fixture
def tab(services, project):
    activity = services.tabs.open("coverage", project.id)
    assert isinstance(activity, CoverageActivity)
    activity.view.resize(1000, 400)
    return activity


def ids(tab, column):
    return [card.item.id for card in tab.scene.lane_cards(column)]


def feature_card(project, title):
    """A feature's card id: its step's, since a feature *is* a step."""
    step = next(s for s in project.steps if s.title == title)
    return f"feature:{step.id}"


def test_the_lanes_hold_the_trace(project, tab):
    assert ids(tab, SPEC) == ["doc:guide", "passage:guide:0", "passage:guide:1"]
    assert ids(tab, FEATURES) == [feature_card(project, "Import"), feature_card(project, "Export")]
    # A milestone, and the bucket for the feature none of them gathers.
    assert len(ids(tab, MILESTONES)) == 2 and ids(tab, MILESTONES)[0].startswith("milestone:")
    assert ids(tab, MILESTONES)[1] == "bucket:none"
    assert len(ids(tab, OUTCOMES)) == 30
    assert len(tab.scene.links) == 2 + 2 + 30
    assert "guide · 2 of 3 paragraphs cited" in tab.summary.text()
    assert not tab.review.isEnabled()


def test_a_pick_lights_the_path_and_scrolls_every_other_lane(project, tab):
    scene = tab.scene
    outcomes = scene.lanes[OUTCOMES]
    outcomes.set_offset(outcomes.max_offset())  # Scrolled to the bottom beforehand.
    assert outcomes.offset > 0
    features = scene.lanes[FEATURES]
    scene.pick(feature_card(project, "Import"))
    lit = {card_id for card_id, card in scene.cards.items() if card.opacity() == 1.0}
    assert lit == tab.trace.path(feature_card(project, "Import")).items
    assert scene.cards[feature_card(project, "Export")].opacity() < 1.0
    assert scene.cards[feature_card(project, "Import")].selected
    assert [link.lit for link in scene.links if link.source.item.id == "passage:guide:1"] == [False]
    assert outcomes.offset == 0.0  # Brought its first lit card into view…
    assert features.offset == 0.0  # …while the picked lane never moved.
    scene.pick(None)
    assert all(card.opacity() == 1.0 for card in scene.cards.values())
    assert all(link.lit is None for link in scene.links)


def test_a_pick_publishes_the_step_and_a_background_pane_stays_quiet(services, project, tab):
    work, imp, _beta, _export = project.steps
    tab.scene.pick(feature_card(project, "Import"))
    assert services.context.current().selected_entities("step") == [imp.id]
    tab.scene.pick("test:T100")
    assert services.context.current().selected_entities("step") == [work.id]
    tab.scene.pick("passage:guide:0")
    assert services.context.current().selected_entities("step") == []
    tab.on_deactivated()
    tab.scene.pick(feature_card(project, "Import"))
    assert services.context.current().selected_entities("step") == []


def test_a_double_click_opens_the_thing(services, project, tab, monkeypatch):
    from dplanner.modules.step_properties.dialog import StepDetailsDialog

    work, imp, _beta, _export = project.steps
    shown = []
    monkeypatch.setattr(
        StepDetailsDialog,
        "exec",
        lambda self: shown.append(
            (
                self.panel.current_step_id(),
                self.panel.tab_bar.tabText(self.panel.tab_bar.currentIndex()),
            )
        ),
    )
    # A feature is a step, so its details open on the Feature tab — the way a test row
    # opens on Tests.
    tab.scene.activated.emit(feature_card(project, "Import"))
    assert shown == [(imp.id, "Feature")]
    tab.scene.activated.emit("test:T101")
    assert shown[-1] == (work.id, "Tests")
    tab.scene.activated.emit("passage:guide:0")
    specs = next(a for a in services.tabs.activities() if a.title.endswith("Specs"))
    assert specs.lit_passages() == ("import a CSV",)


def test_the_lanes_relayout_across_every_width_without_recursing(tab):
    for width in range(240, 1400, 37):
        tab.view.resize(width, 300 + width % 97)
        lanes = tab.scene.lanes
        assert all(lane.rect.width() >= LANE_MIN_W for lane in lanes)
        assert all(isinstance(lane, LaneItem) for lane in lanes)
    assert tab.scene.sceneRect().width() >= 4 * LANE_MIN_W


def test_the_wheel_scrolls_one_lane_and_the_thumb_says_so(tab):
    outcomes = tab.scene.lanes[OUTCOMES]
    assert outcomes.thumb() is not None and outcomes.offset == 0.0
    outcomes.set_offset(96.0)
    assert outcomes.offset == 96.0 and outcomes.thumb().top() > 0
    assert tab.scene.lanes[FEATURES].thumb() is None  # Everything fits: no thumb at all.


def test_the_step_verbs_reach_the_tab(services, project, tab):
    work, imp, beta, _export = project.steps
    plain = Step(title="plain")
    AddNodeCommand(project.id, plain).redo(services.document)

    def on(step_id):
        return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step_id)),)})

    show = services.actions.spec("coverage.show_step")
    assert show.state(on(imp.id)).enabled and show.state(on(beta.id)).enabled
    assert show.state(on(work.id)).enabled  # It carries tests.
    greyed = show.state(on(plain.id))
    assert greyed.enabled is False and greyed.label == NOT_TRACED_REASON
    services.actions.run("coverage.show_step", on(beta.id))
    assert tab.scene.lit == f"milestone:{beta.id}"

    passage = services.actions.spec("coverage.show_passage")
    assert passage.state(on(imp.id)).enabled
    assert passage.state(on(work.id)).enabled  # Reaches the spec through Import.
    assert passage.state(on(plain.id)).label == NO_PASSAGE_REASON
    services.actions.run("coverage.show_passage", on(work.id))
    specs = next(a for a in services.tabs.activities() if a.title.endswith("Specs"))
    assert specs.lit_passages() == ("import a CSV",)


def test_the_specs_tab_jumps_back_to_the_passage(services, project, tab):
    specs = services.tabs.open("specs", project.id)
    specs.select_document("guide")
    editor = specs._editor
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().toPlainText().index("a CSV"))
    editor.setTextCursor(cursor)
    specs.to_coverage.click()
    assert tab.scene.lit == "passage:guide:0"


def test_the_tab_follows_the_project(services, project, tab):
    _work, _imp, beta, _export = project.steps
    services.document.set_module_data(beta.id, MILESTONE_ID, {})
    assert ids(tab, MILESTONES) == ["bucket:none"]
