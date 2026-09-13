"""Compile Docs in the running application: what greys it, what it sends, what one Ctrl+Z
takes back, and what the Docs view shows about it.

The provider is a fake registered into the real registry — ``LLMProvider`` is satisfied
structurally, so nothing here touches a network — and the composition root's own wiring is
what the test drives, so the module cannot pass while production is wired differently.
"""

import time

import pytest

from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.llm import LLMResult, LLMTimeoutError
from dplanner.modules.docs.activity import DOCS_KIND, MARK_ROLE
from dplanner.modules.docs.aspect import (
    COMPILED_ID,
    MODULE_ID,
    read_compiled,
    read_stamp,
    write_state,
)
from dplanner.modules.docs.module import COMPILE_ACTION, NOT_COLLECTOR_REASON, NOTHING_REASON
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
from dplanner.modules.step_milestone.aspect import write as milestone_write


class FakeProvider:
    def __init__(self, *, answer="# Signing in\n\nYou can now sign in.", raises=None):
        self.id = "fake"
        self.label = "Fake"
        self.seen = []
        self._answer = answer
        self._raises = raises

    def is_configured(self):
        return True

    def model(self):
        return "fake-1"

    def complete(self, messages):
        self.seen.append(messages)
        if self._raises is not None:
            raise self._raises
        return LLMResult(text=self._answer, tokens_in=1, tokens_out=2)


def wait_for(app, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the compile never finished"
        app.processEvents()
        time.sleep(0.01)


def select(services, step_id):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step_id)),))


@pytest.fixture
def project(services, make_project):
    """A documented step behind a feature, behind a milestone."""
    library = services.document
    project = make_project("Discovery")
    parser = Step(title="Write the parser")
    auth = Step(title="Auth")
    v1 = Step(title="Release v1")
    for step in (parser, auth, v1):
        AddNodeCommand(project.id, step).redo(library)
    SetEdgesCommand(auth.id, "requires", [parser.id]).redo(library)
    SetEdgesCommand(v1.id, "requires", [auth.id]).redo(library)
    services.undo.push(SetModuleDataCommand(parser.id, MODULE_ID, write_state(True)))
    services.undo.push(SetModuleDataCommand(auth.id, "feature", feature_write()))
    services.undo.push(SetModuleDataCommand(v1.id, "step_milestone", milestone_write("v1")))
    library.set_text(parser.id, MODULE_ID, "Parses queries.")
    return project


def by_title(project, title):
    return next(step for step in project.steps if step.title == title)


@pytest.fixture
def provider(services, monkeypatch):
    """A configured provider, chosen as Settings ▸ LLM would choose one.

    The preference is patched rather than written: ``set_preferred_provider_id`` reaches
    QSettings, and the suite runs on every core — a test must not write into the machine it
    runs on, nor race the worker beside it doing the same.
    """
    fake = FakeProvider()
    services.llm_providers.register(fake)
    monkeypatch.setattr(services.llm, "preferred_provider_id", lambda: "fake")
    return fake


@pytest.fixture
def module(services):
    return next(m for m in services.modules if getattr(m, "id", "") == MODULE_ID)


def state(services):
    return services.actions.spec(COMPILE_ACTION).state(services.context.current())


def compile_it(qapp, services, step_id):
    select(services, step_id)
    services.actions.run(COMPILE_ACTION, services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())


# -- what greys it -----------------------------------------------------------------------------


def test_a_step_that_collects_nothing_says_so_rather_than_hiding_the_verb(services, project):
    select(services, by_title(project, "Write the parser").id)
    answer = state(services)
    assert answer.enabled is False
    assert answer.label == NOT_COLLECTOR_REASON


def test_without_a_provider_the_reason_names_where_to_configure_one(services, project):
    select(services, by_title(project, "Auth").id)
    answer = state(services)
    assert answer.enabled is False
    assert "Settings ▸ LLM" in (answer.label or "")


def test_with_nothing_documented_behind_it_the_reason_says_that(services, project, provider):
    services.document.set_text(by_title(project, "Write the parser").id, MODULE_ID, "")
    select(services, by_title(project, "Auth").id)
    answer = state(services)
    assert answer.enabled is False
    assert answer.label == NOTHING_REASON


def test_a_feature_with_sources_and_a_provider_runs(services, project, provider):
    select(services, by_title(project, "Auth").id)
    assert state(services).enabled is True


def test_the_two_presenters_read_one_reason(services, project, module):
    """The menu entry's label and the view's banner are the same sentence, by construction."""
    auth = by_title(project, "Auth")
    select(services, auth.id)
    runnable, reason = module.compile_state(auth.id)
    assert runnable is False
    assert state(services).label == reason


# -- running it --------------------------------------------------------------------------------


def test_the_document_and_its_stamp_land_as_one_undo_entry(qapp, services, project, provider):
    auth = by_title(project, "Auth")
    compile_it(qapp, services, auth.id)
    assert read_compiled(auth).startswith("# Signing in")
    stamp = read_stamp(auth)
    assert (stamp["provider"], stamp["model"], stamp["sources"]) == ("Fake", "fake-1", 1.0)

    services.undo.undo()
    assert read_compiled(auth) == ""
    assert read_stamp(auth) == {}
    # The fragment is untouched: compiling wrote the other document.
    assert services.document.text(by_title(project, "Write the parser").id, MODULE_ID)


def test_the_prompt_carries_the_house_style_the_brief_and_the_sources(
    qapp, services, project, provider
):
    library = services.document
    library.set_text(project.id, MODULE_ID, "Second person, present tense.")
    library.set_text(by_title(project, "Auth").id, DESCRIPTION_ID, "Write the sign-in guide.")
    compile_it(qapp, services, by_title(project, "Auth").id)

    system, user = provider.seen[0]
    assert system.role == "system"
    assert "Second person, present tense." in user.content
    assert "Write the sign-in guide." in user.content
    assert "## Write the parser" in user.content and "Parses queries." in user.content


def test_a_milestone_is_given_its_features_document_not_the_notes_again(
    qapp, services, project, provider
):
    compile_it(qapp, services, by_title(project, "Auth").id)
    compile_it(qapp, services, by_title(project, "Release v1").id)
    _system, user = provider.seen[-1]
    assert "# Signing in" in user.content
    assert "Parses queries." not in user.content


def test_the_call_shows_up_in_the_llm_call_log_without_this_module_logging_it(
    qapp, services, project, provider
):
    compile_it(qapp, services, by_title(project, "Auth").id)
    assert [record.status for record in services.llm.recent_calls()] == ["ok"]


def test_a_timeout_finishes_the_task_as_timed_out_rather_than_failed(
    qapp, services, project, monkeypatch
):
    services.llm_providers.register(FakeProvider(raises=LLMTimeoutError("too slow")))
    monkeypatch.setattr(services.llm, "preferred_provider_id", lambda: "fake")
    auth = by_title(project, "Auth")
    compile_it(qapp, services, auth.id)
    finished = services.tasks.finished()
    assert finished and finished[-1].timed_out is True
    assert read_compiled(auth) == ""  # Nothing landed.


def test_an_answer_for_a_step_that_stopped_collecting_is_dropped(
    qapp, services, project, provider, module
):
    """The model was thinking; somebody took the feature mark off. The stale answer is not
    text the user asked for any more — github/section.py's guard, for the same reason."""
    auth = by_title(project, "Auth")
    services.undo.push(SetModuleDataCommand(auth.id, "feature", {}))
    module._compiler.compiled.emit(auth.id, "Too late.", "Fake", "fake-1")
    qapp.processEvents()
    assert read_compiled(auth) == ""


# -- the step panel's banner -------------------------------------------------------------------


@pytest.fixture
def docs_section(services):
    """The Docs tab, built the way the step panel builds it."""
    spec = next(s for s in services.inspector_sections.sections() if s.id == "docs.tab")
    section = spec.factory()
    yield section
    section.dispose()


def test_the_banner_says_where_a_collector_stands(qapp, services, project, provider, docs_section):
    auth = by_title(project, "Auth")
    docs_section.show_target(auth.id)
    assert "Not compiled yet" in docs_section.banner.note.text()
    assert docs_section.banner.button.text() == "Compile"

    compile_it(qapp, services, auth.id)
    docs_section.show_target(auth.id)
    assert "Compiled just now" in docs_section.banner.note.text()
    assert docs_section.banner.button.text() == "Recompile"

    services.document.set_text(by_title(project, "Write the parser").id, MODULE_ID, "Changed.")
    docs_section.show_target(auth.id)
    assert "Out of date" in docs_section.banner.note.text()


def test_a_plain_step_gets_no_banner(services, project, docs_section):
    docs_section.show_target(by_title(project, "Write the parser").id)
    assert docs_section.banner.isHidden()


# -- the Docs view -----------------------------------------------------------------------------


@pytest.fixture
def view(services, project):
    return services.tabs.open(DOCS_KIND, project.id)


def rows(view):
    listing = view.page.list
    return [
        (listing.item(i).text(), listing.item(i).data(MARK_ROLE)) for i in range(listing.count())
    ]


def test_the_view_lists_the_collectors_with_their_marks(qapp, services, project, provider, view):
    assert rows(view) == [("Feature: Auth", "never")]

    compile_it(qapp, services, by_title(project, "Auth").id)
    assert rows(view) == [("Feature: Auth", "")]

    services.document.set_text(by_title(project, "Write the parser").id, MODULE_ID, "Changed.")
    assert rows(view) == [("Feature: Auth", "stale")]


def test_grouping_by_milestone_folds_the_feature_in(services, project, view):
    box = view.page.group_box
    box.setCurrentIndex(box.findData("step_milestone"))
    assert [title for title, _mark in rows(view)] == ["Milestone: Release v1"]


def test_a_documented_step_no_feature_reaches_gets_its_own_row(services, project, view):
    library = services.document
    loose = Step(title="Loose end")
    AddNodeCommand(project.id, loose).redo(library)
    library.set_text(loose.id, MODULE_ID, "About the loose end.")
    assert ("Not in any feature", "") in rows(view)


def test_the_two_tabs_show_the_notes_and_the_document(qapp, services, project, provider, view):
    assert [view.page.tabs.tabText(i) for i in range(view.page.tabs.count())] == [
        "Fragments",
        "Compiled",
    ]
    assert "Parses queries." in view.page.fragments.toPlainText()

    compile_it(qapp, services, by_title(project, "Auth").id)
    view.page.list.setCurrentRow(0)
    assert "Signing in" in view.page.compiled.edit.toPlainText()


def test_a_pile_nothing_gathers_has_nothing_to_compile_into(services, project, view):
    library = services.document
    loose = Step(title="Loose end")
    AddNodeCommand(project.id, loose).redo(library)
    library.set_text(loose.id, MODULE_ID, "About the loose end.")
    index = [title for title, _mark in rows(view)].index("Not in any feature")
    view.page.list.setCurrentRow(index)
    # The Compiled tab is not the current one, so ask the widgets themselves rather than
    # whether they are on screen.
    assert not view.page.uncompilable.isHidden()
    assert view.page.banner.isHidden()


def test_editing_the_document_in_the_view_does_not_make_it_stale(
    qapp, services, project, provider, view, module
):
    auth = by_title(project, "Auth")
    compile_it(qapp, services, auth.id)
    services.document.set_text(auth.id, COMPILED_ID, "# Signing in\n\nWith a one-time link.")
    assert module.standing_of(auth.id).state == "current"
