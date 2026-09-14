"""The Coverage tab: lanes, cards and links over a real project; the picks are the
drill-down that fills the lanes to their right; a double-click opens the thing; the
verbs that reach it; and the size hint the splitter has to be able to trust."""

import pytest
from tests.modules.test_spec import imported

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.modules.coverage.activity import CoverageActivity
from dplanner.modules.coverage.module import NO_PASSAGE_REASON, NOT_TRACED_REASON
from dplanner.modules.coverage.scene import (
    GUTTER,
    LANE_MIN_W,
    NOTHING_PROVEN,
    PICK_A_FEATURE,
    LaneItem,
)
from dplanner.modules.coverage.trace import FEATURES, MILESTONES, OUTCOMES, SPEC, STEPS
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


def test_the_lanes_open_on_the_questions_and_the_answers_wait(project, tab):
    """Milestones and features stand from the start; the spec and the outcomes wait to be
    asked for, and say which pick would fill them."""
    assert len(ids(tab, MILESTONES)) == 2 and ids(tab, MILESTONES)[0].startswith("milestone:")
    assert ids(tab, MILESTONES)[1] == "bucket:none"
    assert ids(tab, FEATURES) == [feature_card(project, "Import"), feature_card(project, "Export")]
    assert ids(tab, SPEC) == [] and ids(tab, OUTCOMES) == []
    assert tab.scene.lanes[SPEC].hint == PICK_A_FEATURE
    assert tab.scene.lanes[OUTCOMES].hint == PICK_A_FEATURE
    # Only the lines between two cards that stand are drawn: each feature to its milestone.
    assert len(tab.scene.links) == 2
    assert "guide · 2 of 3 paragraphs cited" in tab.summary.text()
    assert not tab.review_action.isEnabled()


def test_a_milestone_narrows_the_features_and_a_feature_stands_its_spec_and_outcomes(project, tab):
    _work, imp, beta, _export = project.steps
    scene = tab.scene
    scene.pick(f"milestone:{beta.id}")
    assert ids(tab, FEATURES) == [feature_card(project, "Import")]  # Export is under none.
    assert ids(tab, SPEC) == [] and scene.lanes[SPEC].hint == PICK_A_FEATURE
    assert [link.lit for link in scene.links] == [True]

    scene.pick(feature_card(project, "Import"))  # Another lane: the milestone stays picked.
    assert scene.picked == {f"milestone:{beta.id}", feature_card(project, "Import")}
    assert ids(tab, SPEC) == ["doc:guide", "passage:guide:0"]
    assert len(ids(tab, OUTCOMES)) == 30  # The 30 tests behind it, and no other feature's.
    assert len(scene.links) == 1 + 1 + 30
    assert all(link.lit for link in scene.links if link.target == f"feature:{imp.id}")

    # A feature the picked milestone does not gather cannot be stood up beside it.
    scene.pick(feature_card(project, "Export"))
    assert scene.picked == {f"milestone:{beta.id}"} and ids(tab, SPEC) == []


def test_ctrl_click_adds_within_one_lane_and_a_plain_click_replaces(project, tab):
    scene = tab.scene
    scene.pick(feature_card(project, "Import"))
    scene.pick(feature_card(project, "Export"), True)
    assert ids(tab, SPEC) == ["doc:guide", "passage:guide:0", "passage:guide:1"]
    scene.pick(feature_card(project, "Export"), True)  # Picking it again takes it back out.
    assert scene.picked == {feature_card(project, "Import")}
    scene.pick(feature_card(project, "Export"))  # A plain click replaces its lane's picks.
    assert scene.picked == {feature_card(project, "Export")}
    assert ids(tab, SPEC) == ["doc:guide", "passage:guide:1"]
    assert ids(tab, OUTCOMES) == [] and scene.lanes[OUTCOMES].hint == NOTHING_PROVEN
    scene.pick(None)
    assert scene.picked == frozenset() and ids(tab, SPEC) == []


def test_the_steps_lane_stands_between_the_spec_and_the_tests_when_asked_for(
    services, project, tab
):
    """A switch on the strip: the steps each pick holds, and the document's lines to the
    tests rerouted through the steps they sit on — and put back when it is switched off."""
    work, imp, _beta, _export = project.steps
    scene = tab.scene
    assert scene.columns == (MILESTONES, FEATURES, SPEC, OUTCOMES) and ids(tab, STEPS) == []
    tab.steps_action.trigger()
    assert scene.columns == (MILESTONES, FEATURES, SPEC, STEPS, OUTCOMES)
    assert ids(tab, STEPS) == [] and scene.lanes[STEPS].hint == PICK_A_FEATURE

    scene.pick(feature_card(project, "Import"))
    assert ids(tab, STEPS) == [f"step:{work.id}", f"step:{imp.id}"]  # Its work, then itself.
    pairs = {(link.source.item.id, link.target.item.id) for link in scene.links}
    assert ("doc:guide", f"step:{work.id}") in pairs
    assert (f"step:{work.id}", "test:T100") in pairs
    assert not [pair for pair in pairs if pair[0] == "doc:guide" and pair[1].startswith("test:")]
    # Each feature to its milestone, Import to its passage, the document to its two steps,
    # and the step the 30 tests sit on to each of them.
    assert len(scene.links) == 2 + 1 + 2 + 30

    scene.pick(f"step:{work.id}")
    assert services.context.current().selected_entities("step") == [imp.id, work.id]
    tab.steps_action.trigger()  # Switched off: its pick goes with it, and the lines go back.
    assert scene.picked == {feature_card(project, "Import")} and ids(tab, STEPS) == []
    pairs = {(link.source.item.id, link.target.item.id) for link in scene.links}
    assert ("doc:guide", "test:T100") in pairs and len(scene.links) == 2 + 1 + 30


def test_a_card_that_is_a_step_wears_the_spine(project, tab):
    """Milestones, features and steps are steps, named by their key up the card's left edge
    — the canvas's spine, from the one painter both surfaces share. A bucket is no step."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    _work, _imp, beta, _export = project.steps
    scene = tab.scene
    assert scene.cards[feature_card(project, "Import")].item.key == "F2"
    assert scene.cards[f"milestone:{beta.id}"].item.key == "M3"
    assert scene.cards["bucket:none"].item.key == ""

    def strip_and_fill(item_id):
        """The colour just inside the left edge and the body's own, low on the card."""
        card = scene.cards[item_id]
        body = card.mapRectToScene(card.body())
        image = QImage(int(body.width()), int(body.height()), QImage.Format.Format_ARGB32)
        image.fill(scene.palette().window().color())
        painter = QPainter(image)
        scene.render(painter, QRectF(image.rect()), body)
        painter.end()
        low = image.height() - 6  # Under the key and the text: the wash, and the fill.
        return image.pixelColor(6, low).name(), image.pixelColor(image.width() - 20, low).name()

    strip, fill = strip_and_fill(f"milestone:{beta.id}")
    assert strip != fill  # The spine is a shade of its own beside the body.
    strip, fill = strip_and_fill("bucket:none")
    assert strip == fill


def test_a_pick_publishes_every_picked_step_and_a_background_pane_stays_quiet(
    services, project, tab
):
    work, imp, _beta, export = project.steps
    tab.scene.pick(feature_card(project, "Import"))
    assert services.context.current().selected_entities("step") == [imp.id]
    tab.scene.pick(feature_card(project, "Export"), True)
    assert services.context.current().selected_entities("step") == [imp.id, export.id]
    tab.scene.pick("test:T100")  # A test in the outcomes lane: the step it hangs off.
    assert services.context.current().selected_entities("step") == [imp.id, export.id, work.id]
    tab.on_deactivated()  # A background pane does not speak for the user.
    tab.scene.pick(feature_card(project, "Import"))
    assert services.context.current().selected_entities("step") == [imp.id, export.id, work.id]


def test_a_lane_keeps_its_place_across_a_refresh(services, project, tab):
    """A rebuild is a rebuild of the cards, not of what the lane stands: a change
    elsewhere in the project must not scroll the reader back to the top."""
    _work, imp, _beta, _export = project.steps
    tab.scene.pick(feature_card(project, "Import"))
    outcomes = tab.scene.lanes[OUTCOMES]
    outcomes.set_offset(96.0)
    services.document.set_field(imp.id, "title", "Import, renamed")
    services.debounce.flush_all()
    assert [card.item.id for card in outcomes.cards][:1] == ["test:T100"]
    assert outcomes.offset == 96.0
    # But a lane that now stands something else opens at the top.
    outcomes.set_cards(list(outcomes.cards)[:5])
    assert outcomes.offset == 0.0


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
    for arrangement in range(2):  # The four lanes, then with the steps lane between.
        if arrangement:
            tab.steps_action.trigger()
        for width in range(240, 1400, 37):
            tab.view.resize(width, 300 + width % 97)
            lanes = [tab.scene.lanes[column] for column in tab.scene.columns]
            assert all(lane.rect.width() >= LANE_MIN_W for lane in lanes)
            assert all(isinstance(lane, LaneItem) for lane in lanes)
        assert tab.scene.sceneRect().width() >= len(lanes) * LANE_MIN_W


def test_the_view_never_reports_a_width_it_was_given(tab):
    """A ``QGraphicsView``'s own size hint is its scene rect, and this scene is laid to
    the viewport: a splitter honouring that widens the view, which widens the hint."""
    hint, floor = tab.view.sizeHint(), tab.view.minimumSizeHint()
    assert floor.width() < hint.width() < 4 * LANE_MIN_W + 4 * GUTTER
    for width in (400, 900, 1600):
        tab.view.resize(width, 500)
        assert tab.view.sizeHint() == hint
        assert tab.view.minimumSizeHint() == floor
    # And the lanes fit their own extent exactly: no scroll bar comes and goes on a drag.
    tab.view.resize(1200, 500)
    assert tab.scene.sceneRect().width() == 1200


def test_the_wheel_scrolls_one_lane_and_the_thumb_says_so(project, tab):
    tab.scene.pick(feature_card(project, "Import"))  # Its 30 tests overflow the lane.
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
    assert tab.scene.picked == {f"milestone:{beta.id}"}

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
    specs.to_coverage.trigger()
    # Landing on a passage picks what it takes to stand it up: the feature citing it.
    assert tab.scene.picked == {feature_card(project, "Import")}
    assert ids(tab, SPEC) == ["doc:guide", "passage:guide:0"]


def test_the_tab_follows_the_project(services, project, tab):
    _work, _imp, beta, _export = project.steps
    services.document.set_module_data(beta.id, MILESTONE_ID, {})
    assert ids(tab, MILESTONES) == ["bucket:none"]


def test_a_project_with_nothing_to_trace_says_so_where_the_lanes_would_be(services, make_project):
    empty = services.tabs.open("coverage", make_project("Nothing yet").id)
    assert isinstance(empty, CoverageActivity)
    page = empty.widget
    assert empty.empty.isVisibleTo(page) and not empty.view.isVisibleTo(page)
    assert empty.summary.text() == "No spec documents — import one to trace it"
