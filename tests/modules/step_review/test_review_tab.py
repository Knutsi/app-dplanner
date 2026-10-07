"""The review step in the window: the Review template and the Review tab.

W is an agent's work and R its review, waiting on it. Everything runs through the
application the composition root builds, so the wiring is under test as much as the module.
"""

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.step_review.aspect import MODULE_ID as ROUNDS_ID
from dplanner.modules.step_review.aspect import opened, said
from dplanner.planning import agent
from dplanner.planning.review import (
    MODULE_ID,
    ReviewSettings,
    is_review,
    settings,
    write,
)


@pytest.fixture
def project(services, make_project):
    library = services.document
    project = make_project("Discovery")
    work, review = Step(title="Build the parser"), Step(title="Review the parser")
    for step in (work, review):
        AddNodeCommand(project.id, step).redo(library)
        SetModuleDataCommand(step.id, agent.MODULE_ID, agent.write_state(True)).redo(library)
    SetEdgesCommand(review.id, "requires", [work.id]).redo(library)
    return project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


def review_tab(panel):
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    return labels, panel._pages.widget(labels.index("Review"))


def visible(panel):
    return [
        panel.tab_bar.tabText(i)
        for i in range(panel.tab_bar.count())
        if panel.tab_bar.isTabVisible(i)
    ]


def test_the_review_template_is_an_agent_step_that_reviews(services, project, step_editor):
    review = by_title(project, "Review the parser")
    panel = step_editor(review.id)
    assert "Review" not in visible(panel)
    panel.bar.template("Review").trigger()
    assert is_review(review) and agent.enabled(review)
    assert panel.bar.template("Review").isChecked()
    assert "Review" in visible(panel)
    services.undo.undo()  # One undo step, as every template is.
    assert not is_review(review)


def test_the_tab_lays_out_the_agents_the_default_profile_first(services, project, step_editor):
    review = by_title(project, "Review the parser")
    SetModuleDataCommand(review.id, MODULE_ID, write(ReviewSettings())).redo(services.document)
    _labels, tab = review_tab(step_editor(review.id))
    offered = tab.agents()
    assert offered[0][0].startswith("Default profile — ") and offered[0][1] == ""
    assert [agent_id for _words, agent_id in offered[1:]] == ["claude", "codex", "opencode"]
    assert tab.lenses["architecture"].isChecked() and tab.lenses["security"].isChecked()
    assert tab.max_rounds.value() == 3


def test_the_tab_writes_one_undoable_entry(services, project, step_editor):
    review = by_title(project, "Review the parser")
    SetModuleDataCommand(review.id, MODULE_ID, write(ReviewSettings())).redo(services.document)
    _labels, tab = review_tab(step_editor(review.id))
    tab.agent.setCurrentIndex(tab.agent.findData("codex"))
    tab.agent.activated.emit(tab.agent.currentIndex())
    tab.lenses["security"].setChecked(False)
    tab.skills.setText("perf-review")
    tab.skills.editingFinished.emit()
    tab.max_rounds.setValue(2)
    assert settings(review) == ReviewSettings(
        agent="codex", lenses=("architecture", "perf-review"), max_rounds=2
    )
    assert services.undo.undo_text() == "Set Review"


def test_the_conversation_follows_the_ledger_written_outside(services, project, step_editor):
    """The verbs write the ledger from a terminal; the tab shows each message as it lands."""
    library = services.document
    work, review = by_title(project, "Build the parser"), by_title(project, "Review the parser")
    SetModuleDataCommand(review.id, MODULE_ID, write(ReviewSettings())).redo(library)
    _labels, tab = review_tab(step_editor(review.id))
    assert tab.rows() == [] and not tab.empty.isHidden()

    SetModuleDataCommand(review.id, ROUNDS_ID, opened(review, work.id, "t1")).redo(library)
    posted = said(review, work.id, findings="Trailing whitespace.\nMore.", posted="t2")
    SetModuleDataCommand(review.id, ROUNDS_ID, posted).redo(library)
    replied = said(review, work.id, reply="Trimmed.", replied="t3")
    SetModuleDataCommand(review.id, ROUNDS_ID, replied).redo(library)
    keys = [row[0] for row in tab.rows()]
    assert len(keys) == 2 and keys[0].startswith("Round 1 · ") and "findings" in keys[0]
    assert "reply" in keys[1]
    assert [row[1] for row in tab.rows()] == ["Trailing whitespace.", "Trimmed."]
    assert tab.empty.isHidden()
    assert "answered round 1" in tab.standing.words()
