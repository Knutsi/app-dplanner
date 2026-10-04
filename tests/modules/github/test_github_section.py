"""The GitHub tab, as the panel drives it: typing gh-less, picking from fetched lists.

The loader is never started here — the test library has no repository URL, so the section
spawns no subprocess; the fetched lists are handed to ``_on_lists`` directly.
"""

import pytest
from tests.facts import code_row

from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.modules.github import section as section_mod
from dplanner.modules.github.aspect import MODULE_ID, GithubRefs, read
from dplanner.modules.github.gh import PrInfo
from dplanner.modules.github.section import MERGED_COLOUR

MERGED = PrInfo(number=12, title="Add login flow", state="merged", url="u12", head_ref="feat/login")
OPEN = PrInfo(number=7, title="Fix crash", state="open", url="u7", head_ref="fix/crash")


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    AddNodeCommand(project.id, Step(title="Read the spec")).redo(services.document)
    return project


@pytest.fixture
def editor(step_editor, project):
    panel = step_editor(project.steps[0].id)
    labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
    return panel._pages.widget(labels.index("GitHub"))


def test_a_typed_branch_goes_through_the_undo_stack(services, project, editor):
    step = project.steps[0]
    editor.branch_edit.setEditText("feat/login")
    editor.branch_edit.lineEdit().editingFinished.emit()

    assert services.document.step(step.id).module_data[MODULE_ID]["branch"] == "feat/login"
    assert services.undo.undo_text() == "Set GitHub Refs"
    services.undo.undo()
    assert MODULE_ID not in services.document.step(step.id).module_data


def test_a_typed_pr_is_recorded_with_no_state_until_something_checks(services, project, editor):
    step = project.steps[0]
    editor.pr_edit.setEditText("#12")
    editor.pr_edit.lineEdit().editingFinished.emit()

    entry = services.document.step(step.id).module_data[MODULE_ID]
    assert entry["pr_number"] == 12 and "pr_state" not in entry


def test_clearing_both_fields_removes_the_entry(services, project, editor):
    step = project.steps[0]
    editor.branch_edit.setEditText("feat/login")
    editor.branch_edit.lineEdit().editingFinished.emit()
    editor.branch_edit.setEditText("")
    editor.branch_edit.lineEdit().editingFinished.emit()
    assert MODULE_ID not in services.document.step(step.id).module_data


def loaded(editor, branches, prs, message=""):
    """Hand the editor a fetch result the way its loader would, for its current repo."""
    editor._loaded_repo = "acme/widget"
    editor._on_lists("acme/widget", branches, prs, message)


def test_fetched_lists_fill_the_pickers_and_mark_merged_prs_green(editor):
    loaded(editor, ["main", "feat/login"], [OPEN, MERGED])
    assert [editor.branch_edit.itemText(i) for i in range(editor.branch_edit.count())] == [
        "main",
        "feat/login",
    ]
    assert "✓ merged" in editor.pr_edit.itemText(1)
    from PySide6.QtCore import Qt

    brush = editor.pr_edit.itemData(1, Qt.ItemDataRole.ForegroundRole)
    assert brush is not None and brush.color() == MERGED_COLOUR


def test_picking_a_listed_pr_records_its_state_title_url_and_branch(services, project, editor):
    step = project.steps[0]
    loaded(editor, [], [OPEN, MERGED])
    editor.pr_edit.setCurrentIndex(1)
    editor.pr_edit.activated.emit(1)

    refs = read(services.document.step(step.id))
    assert refs is not None
    assert refs.pr_number == 12 and refs.pr_state == "merged" and refs.branch == "feat/login"


def test_a_failed_fetch_leaves_the_fields_typeable_and_says_why(editor):
    loaded(editor, [], [], "gh not found on PATH")
    assert "type values manually" in editor.status.text()
    assert editor.pr_edit.isEditable() and editor.branch_edit.isEditable()


def test_the_projects_code_repository_answers_over_the_plans_origin(services, project, editor):
    """A separated plan: the refs belong to the code repository the project records,
    whatever the plan's own repository is called."""
    from dplanner.domain.commands import SetFieldCommand

    assert editor._repository_for(project.steps[0].id) == ""
    services.undo.push(
        SetFieldCommand(project.id, "locations", code_row("https://github.com/acme/other"))
    )
    assert editor._repository_for(project.steps[0].id) == "https://github.com/acme/other"


def test_no_repository_means_no_fetch_and_a_hint(editor):
    """The fixture library has no repository URL, so showing a step must not have started
    a loader — the status explains what to set instead."""
    assert editor._loaded_repo is None
    assert "repository" in editor.status.text()


# -- where the refs stand ----------------------------------------------------------------------


def with_refs(services, project, refs):
    from dplanner.modules.github.aspect import write

    step = project.steps[0]
    services.undo.push(SetModuleDataCommand(step.id, MODULE_ID, write(refs)))
    return step


def test_the_standing_line_reads_the_fetched_lists(services, project, editor, monkeypatch):
    """The PR's live state and title, and whether the branch is still on the remote — from
    the same answer that fills the pickers."""
    monkeypatch.setattr(section_mod, "parse_repo", lambda _url: "acme/widget")
    with_refs(services, project, GithubRefs(branch="feat/login", pr_number=12))
    assert editor.standing_words() == "PR #12 — not checked yet"
    loaded(editor, ["main"], [OPEN, MERGED])
    assert editor.standing_words() == (
        "PR #12 is merged · Add login flow\n"
        "feat/login is not on the remote — deleted after the merge?"
    )
    assert editor.standing.isVisibleTo(editor)
    loaded(editor, ["main", "feat/login"], [OPEN, MERGED])
    assert editor.standing_words().endswith("feat/login is on the remote")


def test_fresh_pr_state_is_written_into_the_step_off_the_undo_stack(services, project, editor):
    step = with_refs(services, project, GithubRefs(pr_number=12))
    before = services.undo.undo_text()
    loaded(editor, [], [MERGED])
    refs = read(services.document.step(step.id))
    assert refs is not None and refs.pr_state == "merged" and refs.pr_title == "Add login flow"
    assert services.undo.undo_text() == before  # a fact from outside is no undo step


def test_the_open_buttons_hand_the_links_to_the_browser(services, project, editor, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(section_mod, "open_url", opened.append)
    monkeypatch.setattr(section_mod, "parse_repo", lambda _url: "acme/widget")
    assert not editor.open_pr.isEnabled() and not editor.open_branch.isEnabled()
    with_refs(services, project, GithubRefs(branch="feat/login", pr_number=12))
    assert editor.open_pr.isEnabled() and editor.open_branch.isEnabled()
    editor.open_pr.click()
    editor.open_branch.click()
    assert opened == [
        "https://github.com/acme/widget/pull/12",
        "https://github.com/acme/widget/tree/feat/login",
    ]
    # A recorded URL wins over the one built from the number.
    with_refs(services, project, GithubRefs(pr_number=12, pr_url="https://gh/x/pull/12"))
    editor.open_pr.click()
    assert opened[-1] == "https://gh/x/pull/12"


def test_without_a_github_repository_there_is_nothing_to_open(services, project, editor):
    with_refs(services, project, GithubRefs(branch="feat/login", pr_number=12))
    assert not editor.open_pr.isEnabled() and not editor.open_branch.isEnabled()
    assert editor.standing_words() == "PR #12 — not checked yet"


def test_a_stale_answer_is_asked_for_again_on_the_next_show(services, project, editor, monkeypatch):
    """Within the TTL a show costs nothing; past it the same repository is fetched again,
    so the standing line is current when the tab opens."""
    started: list[str] = []

    def fake_run(title, _body, **_kw):
        started.append(title)
        return True

    monkeypatch.setattr(section_mod, "parse_repo", lambda _url: "acme/widget")
    monkeypatch.setattr(editor._runner, "run", fake_run)
    editor.show_target(project.steps[0].id)
    assert len(started) == 1
    loaded(editor, ["main"], [])
    editor.show_target(project.steps[0].id)
    assert len(started) == 1  # fresh enough
    editor._loaded_at -= section_mod.LISTS_TTL_S + 1
    editor.show_target(project.steps[0].id)
    assert len(started) == 2
