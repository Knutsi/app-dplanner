"""A conversation read in full: *Step ▸ Review Conversation…*, the dialog it opens, and the
Review tab's two ways into it.

W is an agent's work and R its review, waiting on it; P is a plain step. The ledger is
written the way the ``review`` verbs write it, straight into the model, and everything else
runs through the application the composition root builds.
"""

import pytest
from tests.modules.step_review.test_review_tab import by_title, review_tab

from dplanner.domain.commands import (
    AddNodeCommand,
    RemoveNodeCommand,
    SetEdgesCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, Context, ContextNode, selection_uri
from dplanner.modules.step_review.aspect import ASKER, PARTY, opened, said
from dplanner.modules.step_review.aspect import MODULE_ID as ROUNDS_ID
from dplanner.modules.step_review.conversation_dialog import ConversationDialog
from dplanner.planning import agent
from dplanner.planning.review import MODULE_ID, ReviewSettings, write

VERB = "review.conversation"
FINDINGS = "The error for an unclosed quote names no line.\n\nSay where the quote opened."


@pytest.fixture
def project(services, make_project):
    library = services.document
    project = make_project("Discovery")
    work, review, plain = Step(title="W"), Step(title="R"), Step(title="P")
    for step in (work, review, plain):
        AddNodeCommand(project.id, step).redo(library)
    for step in (work, review):
        SetModuleDataCommand(step.id, agent.MODULE_ID, agent.write_state(True)).redo(library)
    SetModuleDataCommand(review.id, MODULE_ID, write(ReviewSettings())).redo(library)
    SetEdgesCommand(review.id, "requires", [work.id]).redo(library)
    return project


def write_round(library, asker, party, stamp, **fields):
    """What ``review start`` and the verbs after it leave: a round opened, then its fields."""
    SetModuleDataCommand(asker.id, ROUNDS_ID, opened(asker, party.id, stamp)).redo(library)
    if fields:
        stamp_fields(library, asker, party, **fields)


def stamp_fields(library, asker, party, **fields):
    SetModuleDataCommand(asker.id, ROUNDS_ID, said(asker, party.id, **fields)).redo(library)


def two_rounds(library, project):
    """Round 1 answered; round 2's findings waiting on W."""
    work, review = by_title(project, "W"), by_title(project, "R")
    write_round(
        library,
        review,
        work,
        "2026-09-27T11:00:00+00:00",
        findings="The parser drops trailing whitespace.",
        posted="2026-09-27T11:12:00+00:00",
        reply="Kept now, with a test.",
        replied="2026-09-27T12:40:00+00:00",
    )
    write_round(
        library,
        review,
        work,
        "2026-09-27T13:00:00+00:00",
        findings=FINDINGS,
        posted="2026-09-27T13:05:00+00:00",
    )
    return work, review


def about(step):
    return Context({SCOPE_SELECTION: (ContextNode(selection_uri("step", step.id)),)})


@pytest.fixture
def seen(monkeypatch):
    """What each dialog the verb opened showed, read while it was up — ``exec`` stood in for,
    since the dialog is disposed the moment it returns."""
    shown: list[dict[str, object]] = []

    def exec_(dialog):
        shown.append(
            {
                "rows": dialog.rows(),
                "picked": dialog.picked(),
                "text": dialog.shown_text(),
                "where": dialog.status.words(),
            }
        )
        return 0

    monkeypatch.setattr(ConversationDialog, "exec", exec_)
    return shown


@pytest.fixture
def dialog_on(services):
    """A dialog built directly, for the tests that write the ledger while it is up."""
    built = []

    def build(step, **kwargs):
        dialog = ConversationDialog(services.document, step.id, lambda each: "", **kwargs)
        built.append(dialog)
        return dialog

    yield build
    for dialog in built:
        dialog.dispose()
        dialog.deleteLater()


# -- the verb -------------------------------------------------------------------------------


def test_it_is_greyed_with_why_until_a_round_is_asked(services, project):
    work, review, plain = (by_title(project, title) for title in ("W", "R", "P"))
    spec = services.actions.spec(VERB)

    for step, reason in ((plain, "not a review"), (review, "no rounds yet")):
        state = spec.state(about(step))
        assert not state.enabled
        assert state.label == f"Review Conversation — {reason}"

    write_round(services.document, review, work, "2026-09-27T11:00:00+00:00")
    assert spec.state(about(review)).enabled


def test_it_lists_every_message_and_opens_on_the_newest_in_full(services, project, seen):
    two_rounds(services.document, project)
    services.actions.run(VERB, about(by_title(project, "R")))

    ((shown),) = seen
    headings = [heading for heading, _line, _sender in shown["rows"]]
    assert [heading.split(" · ")[0] for heading in headings] == ["Round 1", "Round 1", "Round 2"]
    assert "findings" in headings[0] and "reply" in headings[1]
    assert [sender for _heading, _line, sender in shown["rows"]] == [ASKER, PARTY, ASKER]
    assert shown["rows"][2][1] == FINDINGS.splitlines()[0]  # The list gives the first line.
    assert shown["picked"] == 2
    assert "Say where the quote opened." in shown["text"]  # The dialog gives all of it.
    assert "round 2" in shown["where"] and "2 of 3 rounds" in shown["where"]


def test_the_sender_wears_its_glyph(services, project, dialog_on):
    _work, review = two_rounds(services.document, project)
    dialog = dialog_on(review)
    icons = [dialog.messages.item(index).icon() for index in range(dialog.messages.count())]
    assert not any(icon.isNull() for icon in icons)
    asker, party = icons[0].pixmap(16).toImage(), icons[1].pixmap(16).toImage()
    assert asker != party  # The review's glyph, then the agent's.


def test_picking_a_message_shows_it_and_an_approval_says_who(services, project, dialog_on):
    work, review = two_rounds(services.document, project)
    dialog = dialog_on(review)

    dialog.messages.setCurrentRow(1)
    assert dialog.shown_text() == "Kept now, with a test."
    assert "reply" in dialog.heading.text()

    stamp_fields(services.document, review, work, approved="2026-09-27T14:00:00+00:00")
    dialog.messages.setCurrentRow(dialog.messages.count() - 1)
    assert dialog.heading.text().endswith("Approved")
    assert "approved" in dialog.shown_text() and "round 2" in dialog.shown_text()
    assert dialog.status.tone() == "ok"


def test_it_follows_the_ledger_and_keeps_the_readers_place(services, project, dialog_on):
    work, review = two_rounds(services.document, project)
    dialog = dialog_on(review)
    dialog.messages.setCurrentRow(0)
    before = dialog.status.words()

    stamp_fields(
        services.document,
        review,
        work,
        reply="Every refusal names its line now.",
        replied="2026-09-27T15:00:00+00:00",
    )
    assert len(dialog.rows()) == 4 and dialog.rows()[3][2] == PARTY
    assert dialog.picked() == 0 and "trailing whitespace" in dialog.shown_text()
    assert dialog.status.words() != before and "answered round 2" in dialog.status.words()


def test_a_stamp_that_says_nothing_leaves_the_text_where_it_was_read(services, project, dialog_on):
    """``review take`` stamps the round and adds no message: the reader keeps their place."""
    work, review = two_rounds(services.document, project)
    dialog = dialog_on(review)
    rendered = []
    dialog.text.document().contentsChanged.connect(lambda: rendered.append(True))
    stamp_fields(services.document, review, work, taken="2026-09-27T13:30:00+00:00")
    assert rendered == [] and dialog.picked() == 2
    assert "is working on" in dialog.status.words()


def test_it_closes_when_its_step_is_deleted(services, project, dialog_on):
    _work, review = two_rounds(services.document, project)
    dialog = dialog_on(review)
    dialog.show()
    RemoveNodeCommand(review.id).redo(services.document)
    assert not dialog.isVisible()


def test_a_collector_talking_to_two_sources_names_each(services, make_project, dialog_on):
    """A collector sends work upstream with the same verbs, so its ledger reads the same —
    and with two parties, each heading says which one."""
    library = services.document
    project = make_project("Collecting")
    a1, a2, collector = Step(title="A1"), Step(title="A2"), Step(title="C")
    for step in (a1, a2, collector):
        AddNodeCommand(project.id, step).redo(library)
    SetEdgesCommand(collector.id, "requires", [a1.id, a2.id]).redo(library)
    for source in (a1, a2):
        write_round(library, collector, source, "t1", findings="Not ready.", posted="t2")

    assert services.actions.spec(VERB).state(about(collector)).enabled
    dialog = dialog_on(collector)
    headings = [heading for heading, _line, _sender in dialog.rows()]
    assert len(headings) == 2
    assert all(heading.startswith("Round 1 with ") for heading in headings)
    assert headings[0] != headings[1]


# -- the ways in ----------------------------------------------------------------------------


def test_the_review_tab_opens_it_on_the_newest_or_on_a_row(services, project, step_editor, seen):
    review = by_title(project, "R")
    _labels, tab = review_tab(step_editor(review.id))
    assert not tab.conversation_button.isEnabled()  # Nothing said yet.

    two_rounds(services.document, project)
    assert tab.conversation_button.isEnabled()
    tab.conversation_button.click()
    tab.conversation.itemActivated.emit(tab.conversation.item(0))
    assert [shown["picked"] for shown in seen] == [2, 0]
    assert seen[1]["text"] == "The parser drops trailing whitespace."


def test_a_review_cards_right_click_offers_it(services, project):
    from tests.modules.canvas.test_canvas import centre_of, labels, offered, scene

    two_rounds(services.document, project)
    tab = services.tabs.open("project", project.id)
    review, plain = by_title(project, "R"), by_title(project, "P")
    assert "Review Conversation…" in labels(offered(tab, centre_of(scene(tab).node(review.id))))
    assert "Review Conversation — not a review" in labels(
        offered(tab, centre_of(scene(tab).node(plain.id)))
    )
