"""Compiling in the running application: what greys the verb, what the launched agent is
handed, what the run leaves on the collector, and what the Documentation view shows.

The terminal is faked the way every other launch test fakes it — ``launcher.resolve_command``
and ``launcher.spawn`` patched on the module object — so no shell opens and the prompt file on
disk is what the assertions read. The composition root's own wiring is what the test drives,
so the module cannot pass while production is wired differently.
"""

from pathlib import Path
from typing import ClassVar

import pytest

from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import (
    AddNodeCommand,
    SetEdgesCommand,
    SetFieldCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.list_rows import DETAIL_ROLE, TRAILING_ROLE
from dplanner.framework.user_config import set_global
from dplanner.modules.docs import module as docs_module
from dplanner.modules.docs.activity import DOCS_KIND
from dplanner.modules.docs.aspect import COMPILED_ID, MODULE_ID, write_state
from dplanner.modules.docs.module import (
    COMPILE_ACTION,
    COMPILE_MENU_ID,
    LAUNCHES_KEY,
    NOT_COLLECTOR_REASON,
    NOTHING_REASON,
    STALE_ACTION,
)
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction import module as agent_module
from dplanner.modules.step_agent_run.aspect import read as run_state
from dplanner.modules.step_milestone.aspect import write as milestone_write


@pytest.fixture
def terminal(monkeypatch):
    """A terminal that always opens and never runs anything: the commands it was handed."""
    opened: list[list[str]] = []

    def spawn(command, _workdir, **_kwargs):
        opened.append(command)
        return ""  # "" is a shell that started; a reason string is one that did not.

    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: ["fake-term"])
    monkeypatch.setattr(launcher, "spawn", spawn)
    return opened


@pytest.fixture
def no_terminal(monkeypatch):
    """No terminal on this machine, and a fallback dialog that shows nothing."""

    class SilentDialog:
        shown: ClassVar[list[str]] = []

        def __init__(self, text, *_args, **_kwargs):
            SilentDialog.shown.append(text)

        def exec(self):
            return 0

    SilentDialog.shown = []
    monkeypatch.setattr(launcher, "resolve_command", lambda *a, **k: None)
    monkeypatch.setattr(agent_module, "PromptFallbackDialog", SilentDialog)
    return SilentDialog


def select(services, step_id):
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step_id)),))


def select_project(services, project_id):
    node = ContextNode(selection_uri("project", project_id))
    services.context.set_scope(SCOPE_SELECTION, (node,))


@pytest.fixture
def project(services, make_project, tmp_path):
    """A documented step behind a feature, behind a milestone, in a checkout that exists."""
    library = services.document
    project = make_project("Discovery")
    code = init_repo(tmp_path / "widget")
    services.undo.push(SetFieldCommand(project.id, "repository", "https://example.com/widget"))
    services.repo.set_checkout(project.id, code)
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
def module(services):
    return next(m for m in services.modules if getattr(m, "id", "") == MODULE_ID)


def state(services, action_id=COMPILE_ACTION):
    return services.actions.spec(action_id).state(services.context.current())


def compile_it(services, step_id):
    select(services, step_id)
    services.actions.run(COMPILE_ACTION, services.context.current())


def runs(services):
    """The runs the tracker holds — how a launch's own files are found, as the Agents
    browser finds them."""
    tracker = next(m for m in services.modules if getattr(m, "id", "") == "step_agent_run")
    return tracker.runs()


def briefing(services):
    """What the agent was told to read: prompt.md as it actually reached the run."""
    tracked = runs(services)
    assert tracked, "no run was tracked"
    return (Path(tracked[-1].shell_file).parent / "prompt.md").read_text()


@pytest.fixture
def replacing(monkeypatch):
    """The question a compile asks before an agent replaces a document that has text, and
    what it was asked — answered yes. A modal `exec()` in a test hangs the suite."""
    asked: list[str] = []

    def yes(_parent, _title, question, **_kw):
        asked.append(question)
        return True

    monkeypatch.setattr(docs_module, "confirm", yes)
    return asked


@pytest.fixture
def refusing(monkeypatch):
    asked: list[str] = []

    def no(_parent, _title, question, **_kw):
        asked.append(question)
        return False

    monkeypatch.setattr(docs_module, "confirm", no)
    return asked


# -- what greys it -----------------------------------------------------------------------------


def test_a_step_that_collects_nothing_says_so_rather_than_hiding_the_verb(services, project):
    select(services, by_title(project, "Write the parser").id)
    greyed = state(services)
    assert greyed.enabled is False
    assert greyed.label == NOT_COLLECTOR_REASON


def test_a_collector_with_no_fragments_behind_it_cannot_compile(services, project):
    services.document.set_text(by_title(project, "Write the parser").id, MODULE_ID, "")
    select(services, by_title(project, "Auth").id)
    greyed = state(services)
    assert greyed.enabled is False
    assert greyed.label == NOTHING_REASON


def test_a_project_with_no_checkout_here_says_so(services, project, terminal):
    services.repo.set_checkout(project.id, None)
    select(services, by_title(project, "Auth").id)
    greyed = state(services)
    assert greyed.enabled is False
    assert "not checked out" in greyed.label


def test_a_collector_with_fragments_and_a_checkout_can_compile(services, project, terminal):
    select(services, by_title(project, "Auth").id)
    assert state(services).enabled is True


def test_running_it_without_a_terminal_hands_the_briefing_over_instead(
    services, project, no_terminal
):
    compile_it(services, by_title(project, "Auth").id)
    assert no_terminal.shown, "the prompt was lost with the missing terminal"
    assert "Parses queries." in no_terminal.shown[0]


# -- what the agent is handed --------------------------------------------------------------------


def test_the_briefing_carries_the_instructions_the_fragments_and_the_finishing_verb(
    services, project, terminal
):
    library = services.document
    library.set_text(project.id, MODULE_ID, "Second person, present tense.")
    library.set_text(by_title(project, "Auth").id, "step_description", "Signing in with a link.")
    compile_it(services, by_title(project, "Auth").id)

    text = briefing(services)
    assert "Second person, present tense." in text  # The compilation instructions.
    assert "Signing in with a link." in text  # What the collector says about itself.
    assert "Parses queries." in text  # What the work documented.
    assert "dplanner compiled set F2 --file -" in text  # Keyed by the step's key.
    assert "## Before you start" in text  # The launcher's own preflight, around it all.


def test_a_milestone_is_briefed_with_its_features_document_not_their_fragments_again(
    services, project, terminal
):
    library = services.document
    auth = by_title(project, "Auth")
    library.set_text(auth.id, COMPILED_ID, "# Signing in")
    compile_it(services, by_title(project, "Release v1").id)

    text = briefing(services)
    assert "# Signing in" in text
    assert "Parses queries." not in text


def test_the_run_is_tracked_on_the_collector_and_claims_nothing_about_the_work(
    services, project, terminal, module
):
    auth = by_title(project, "Auth")
    compile_it(services, auth.id)
    # The chip says a shell is open on this step, so the Agents browser can reach it...
    assert run_state(services.document.step(auth.id)) == "launched"
    # ...and the step's *status* is untouched: an agent writing a feature's documentation is
    # not doing that feature's work.
    assert "step_status" not in services.document.step(auth.id).module_data


def test_the_launch_is_remembered_as_this_desks_own_and_says_so_on_the_row(
    services, project, terminal, module
):
    auth = by_title(project, "Auth")
    compile_it(services, auth.id)
    assert "session" in module.standing_of(auth.id).by


def test_the_terminals_window_says_what_the_run_is_for(services, project, terminal):
    """Two runs on one step are told apart by their windows or not at all: a feature can be
    an agent step, so a compile's terminal must not be titled exactly as its work run's."""
    compile_it(services, by_title(project, "Auth").id)
    [tracked] = runs(services)
    script = Path(tracked.shell_file).parent / "run.sh"
    assert "(documentation)" in script.read_text()


# -- compiling everything that is out of date ----------------------------------------------------


def test_a_milestone_waits_for_the_feature_whose_document_it_reads(services, project, terminal):
    """One gesture takes the frontier: a milestone launched beside its features would read a
    document that is about to change."""
    select_project(services, project.id)
    greyed = state(services, STALE_ACTION)
    assert greyed.enabled is True
    assert "1 waiting" in greyed.label

    services.actions.run(STALE_ACTION, services.context.current())
    assert len(terminal) == 1
    assert "Parses queries." in briefing(services)


def test_a_project_whose_documents_are_all_current_offers_nothing(services, project, terminal):
    landed(services, project, by_title(project, "Auth"))
    landed(services, project, by_title(project, "Release v1"))
    select_project(services, project.id)
    greyed = state(services, STALE_ACTION)
    assert greyed.enabled is False
    assert "up to date" in greyed.label


def test_only_the_milestone_is_due_once_its_feature_is_current(services, project, terminal):
    """With the feature's document current, the milestone is the one thing to compile — and
    nothing waits on anything."""
    auth = by_title(project, "Auth")
    landed(services, project, auth)
    select_project(services, project.id)
    ready = state(services, STALE_ACTION)
    assert ready.enabled is True
    assert "waiting" not in ready.label

    services.actions.run(STALE_ACTION, services.context.current())
    assert len(terminal) == 1
    assert "# Signing in" in briefing(services)  # The milestone reads the feature's document.


def test_the_out_of_date_label_reads_a_settled_answer_and_never_walks_the_graph(
    services, project, terminal, monkeypatch
):
    """An action's state runs on every context announce — every keystroke — so it reads the
    frontier as last settled. The walk runs once per burst, after the change, and the settle
    announces the context so the menu bar's label catches up."""
    import dplanner.modules.docs.collect as collect

    services.debounce.set_immediate(False)
    select_project(services, project.id)
    asked = state(services, STALE_ACTION)
    assert asked.enabled is False and "checking" in asked.label  # Owed, not computed here.
    services.debounce.flush_all()
    ready = state(services, STALE_ACTION)
    assert ready.enabled is True and "1 waiting" in ready.label

    walks = []
    real = collect.sources_for

    def counted(*args):
        walks.append(args)
        return real(*args)

    monkeypatch.setattr(collect, "sources_for", counted)
    for _ in range(10):
        assert state(services, STALE_ACTION).label == ready.label
    assert walks == []

    heard = []
    services.context.changed.connect(lambda _context: heard.append(True))
    landed(services, project, by_title(project, "Auth"))
    landed(services, project, by_title(project, "Release v1"))
    walks.clear()  # `landed` digests what it lands; the state must add nothing to that.
    # Until the burst settles the label says what it last knew, and nothing has walked...
    assert state(services, STALE_ACTION).label == ready.label
    assert walks == []
    services.debounce.flush_all()
    # ...then one settle recomputes it and announces the context.
    settled = state(services, STALE_ACTION)
    assert settled.enabled is False and "up to date" in settled.label
    assert heard


def test_compiling_out_of_date_reads_the_plan_as_it_is_not_as_the_label_last_saw_it(
    services, project, terminal
):
    services.debounce.set_immediate(False)
    select_project(services, project.id)
    services.debounce.flush_all()
    assert "1 waiting" in state(services, STALE_ACTION).label
    landed(services, project, by_title(project, "Auth"))
    # The label still owes a settle; the gesture does not wait for it.
    services.actions.run(STALE_ACTION, services.context.current())
    assert len(terminal) == 1
    assert "# Signing in" in briefing(services)  # The milestone, reading the landed document.


def test_replacing_a_document_that_has_text_is_asked_about_once(
    services, project, terminal, replacing
):
    """The agent's write arrives from another process, so Ctrl+Z is not the safety net it is
    everywhere else."""
    auth = by_title(project, "Auth")
    landed(services, project, auth)
    compile_it(services, auth.id)
    assert len(replacing) == 1
    assert "no undo" in replacing[0]
    assert len(terminal) == 1


def test_saying_no_launches_nothing(services, project, terminal, refusing):
    auth = by_title(project, "Auth")
    landed(services, project, auth)
    compile_it(services, auth.id)
    assert refusing and terminal == []


# -- the step panel's line -----------------------------------------------------------------------


@pytest.fixture
def docs_section(services):
    """The fragment tab, built the way the step panel builds it."""
    spec = next(s for s in services.inspector_sections.sections() if s.id == "docs.tab")
    section = spec.factory()
    yield section
    section.dispose()


def test_the_line_says_where_a_collector_stands(services, project, docs_section):
    auth = by_title(project, "Auth")
    docs_section.show_target(auth.id)
    assert "Not compiled yet" in docs_section.standing.words()

    landed(services, project, auth)
    assert "Up to date" in docs_section.standing.words()
    assert docs_section.standing.tone() == "ok"

    services.document.set_text(by_title(project, "Write the parser").id, MODULE_ID, "Changed.")
    assert "Out of date" in docs_section.standing.words()


def test_the_line_hears_a_fragment_edited_somewhere_else(services, project, docs_section):
    """The panel re-asks which tabs to show on a model change but does not re-show a section,
    so the line follows the model itself."""
    auth = by_title(project, "Auth")
    docs_section.show_target(auth.id)
    landed(services, project, auth)
    assert "Up to date" in docs_section.standing.words()
    services.document.set_text(by_title(project, "Write the parser").id, MODULE_ID, "Changed.")
    assert "Out of date" in docs_section.standing.words()


def test_a_plain_step_gets_no_line(services, project, docs_section):
    docs_section.show_target(by_title(project, "Write the parser").id)
    assert docs_section.standing.isHidden()


def test_an_agent_at_work_on_the_step_is_said_in_the_busy_tone(
    services, project, terminal, docs_section
):
    auth = by_title(project, "Auth")
    compile_it(services, auth.id)
    docs_section.show_target(auth.id)
    assert "An agent is working on this step" in docs_section.standing.words()
    assert docs_section.standing.tone() == "busy"


def landed(services, project, step):
    """What the agent's `dplanner compiled set` amounts to, arriving as a foreign write."""
    from dplanner.modules.docs.aspect import write_stamp
    from dplanner.modules.docs.collect import digest, sources_for

    library = services.document
    scopes = next(m for m in services.modules if getattr(m, "id", "") == MODULE_ID)._deps.scopes
    library.set_text(step.id, COMPILED_ID, "# Signing in")
    found = sources_for(scopes, library, project, step.id)
    library.set_module_data(step.id, COMPILED_ID, write_stamp(digest(found), 1.0, len(found)))


# -- the Documentation view ----------------------------------------------------------------------


@pytest.fixture
def view(services, project):
    return services.tabs.open(DOCS_KIND, project.id)


def rows(view):
    listing = view.page.list
    return [
        (listing.item(i).text(), listing.item(i).data(TRAILING_ROLE))
        for i in range(listing.count())
    ]


def test_the_view_lists_the_collectors_with_their_state_in_words(services, project, view):
    auth = by_title(project, "Auth")
    assert rows(view) == [("F2 · Auth", "not compiled yet")]

    landed(services, project, auth)
    # A document nobody need act on says when it landed instead: the trailing slot is a
    # fact about the row, and "up to date" is what the absence of a state word means.
    [(_title, mark)] = rows(view)
    assert "ago" in mark or mark == "just now"

    services.document.set_text(by_title(project, "Write the parser").id, MODULE_ID, "Changed.")
    assert rows(view) == [("F2 · Auth", "out of date")]


def test_a_row_says_when_it_was_compiled_and_by_whom(services, project, view, module):
    auth = by_title(project, "Auth")
    set_global(MODULE_ID, LAUNCHES_KEY, {auth.id: "Claude Code · session 3f2a"})
    landed(services, project, auth)
    detail = view.page.list.item(0).data(DETAIL_ROLE)
    assert "Claude Code" in detail
    assert "3f2a" not in detail  # The session is the row's tooltip, not its second line.
    assert "3f2a" in view.page.list.item(0).toolTip()


def test_grouping_by_milestone_folds_the_feature_in(services, project, view):
    box = view.page.group_box
    box.setCurrentIndex(box.findData("step_milestone"))
    assert [title for title, _mark in rows(view)] == ["M3 · Release v1"]


def test_a_documented_step_no_feature_reaches_gets_its_own_row(services, project, view):
    library = services.document
    loose = Step(title="Loose end")
    AddNodeCommand(project.id, loose).redo(library)
    library.set_text(loose.id, MODULE_ID, "About the loose end.")
    assert ("Not in any feature", "") in rows(view)


def test_the_three_tabs_are_the_fragments_the_document_and_the_instructions(
    services, project, view
):
    assert [view.page.tabs.tabText(i) for i in range(view.page.tabs.count())] == [
        "Fragments",
        "Documentation",
        "Compilation instructions",
    ]
    assert "Parses queries." in view.page.fragments.toPlainText()


def test_the_instructions_tab_edits_the_projects_own_document(services, project, view):
    services.document.set_text(project.id, MODULE_ID, "Second person.")
    view.page.instructions.show_target(project.id)
    assert "Second person." in view.page.instructions.edit.toPlainText()


def test_the_strip_carries_the_verbs_and_greys_them_with_their_reasons(services, project, view):
    """The strip renders the registry's own state, and a rebuild refreshes the context so a
    fragment deleted elsewhere greys the verb where it stands."""
    view.page.list.setCurrentRow(0)
    assert view.page.verbs[COMPILE_ACTION].isEnabled() is True
    services.document.set_text(by_title(project, "Write the parser").id, MODULE_ID, "")
    services.debounce.flush_all()
    assert view.page.verbs[COMPILE_ACTION].isEnabled() is False
    assert NOTHING_REASON in view.page.verbs[COMPILE_ACTION].toolTip()


def test_the_strips_arrow_drops_the_launch_profiles(services, project, view):
    """The Step menu's own child menu, never a copy of its list."""
    view.page.list.setCurrentRow(0)
    menu = view.page.controls.menu_for(COMPILE_ACTION)
    assert menu is not None
    labels = [action.text() for action in menu.actions() if action.text()]
    assert any("(default)" in label for label in labels)
    assert any("Manage Agent Profiles" in label for label in labels)


def test_the_profile_menu_is_the_same_one_the_step_menu_offers(services, project, view):
    assert services.actions.data_menu(COMPILE_MENU_ID).menu == "Step"


def test_a_pile_nothing_gathers_has_nothing_to_compile_into(services, project, view):
    library = services.document
    loose = Step(title="Loose end")
    AddNodeCommand(project.id, loose).redo(library)
    library.set_text(loose.id, MODULE_ID, "About the loose end.")
    index = [title for title, _mark in rows(view)].index("Not in any feature")
    view.page.list.setCurrentRow(index)
    assert not view.page.uncompilable.isHidden()
    assert view.page.standing.isHidden()


def test_editing_the_document_in_the_view_does_not_make_it_stale(services, project, view, module):
    auth = by_title(project, "Auth")
    landed(services, project, auth)
    services.document.set_text(auth.id, COMPILED_ID, "# Signing in\n\nWith a one-time link.")
    assert module.standing_of(auth.id).state == "current"
