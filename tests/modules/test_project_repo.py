"""The repo association: its shape, its one resolution rule, and the hosted fields."""

import pytest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Product, Project
from dplanner.modules.project_repo import fields as fields_module
from dplanner.modules.project_repo.repo import (
    MODULE_ID,
    checkout_for,
    read_checkout,
    read_repository,
    repository_for,
    write_association,
)

# -- the headless half -------------------------------------------------------------------------


def test_write_strips_and_drops_empties():
    entry = write_association("  https://github.com/o/r  ", "")
    assert entry == {"repository": "https://github.com/o/r", "format": 1}
    assert write_association("", "   ") == {}


def test_reads_are_tolerant_of_junk():
    project = Project(title="P")
    project.module_data[MODULE_ID] = {"repository": 7, "checkout": None, "format": 1}
    assert read_repository(project) == ""
    assert read_checkout(project) == ""


def test_the_project_overrides_the_product():
    product = Product(name="W", checkout="~/Code/mono", repository="https://mono")
    project = Project(title="P")
    product.add_child(product.id, project)
    assert checkout_for(product, project) == "~/Code/mono"
    assert repository_for(product, project) == "https://mono"
    project.module_data[MODULE_ID] = write_association("https://sat", "~/Code/sat")
    assert checkout_for(product, project) == "~/Code/sat"
    assert repository_for(product, project) == "https://sat"


def test_neither_set_resolves_to_nothing():
    product = Product(name="W")
    project = Project(title="P")
    product.add_child(product.id, project)
    assert checkout_for(product, project) == ""


# -- the hosted fields -------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _quiet_probes(monkeypatch):
    """Never a subprocess in tests: the auth cache is pre-answered, so no probe starts."""
    monkeypatch.setattr(fields_module, "_gh_auth_cache", True)


@pytest.fixture
def project(services):
    product = services.document
    project = Project(title="Discovery")
    AddNodeCommand(product.id, project).redo(product)
    return project


@pytest.fixture
def panel(services, project):
    from dplanner.framework.context import (
        SCOPE_SELECTION,
        ContextNode,
        selection_uri,
    )

    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    return services.window.dock.widget_for("project_editor.project")


def test_the_panel_hosts_the_fields(services, project, panel):
    assert panel._repo_fields is not None
    fields = panel._repo_fields
    assert fields.checkout.isEnabled()


def test_typing_a_checkout_commits_one_undoable_command(services, project, panel):
    fields = panel._repo_fields
    fields.checkout.setText("~/Code/widget")
    fields.checkout.editingFinished.emit()
    assert read_checkout(project) == "~/Code/widget"
    services.undo.undo()
    assert read_checkout(project) == ""
    assert MODULE_ID not in project.module_data


def test_an_external_write_echoes_into_the_fields(services, project, panel):
    fields = panel._repo_fields
    services.document.set_module_data(
        project.id, MODULE_ID, write_association("https://sat", "")
    )
    assert fields.repository.text() == "https://sat"


def test_retargeting_swaps_values(services, project, panel):
    other = Project(title="Second")
    AddNodeCommand(services.document.id, other).redo(services.document)
    services.document.set_module_data(other.id, MODULE_ID, write_association("", "~/two"))
    fields = panel._repo_fields
    fields.set_project(other.id)
    assert fields.checkout.text() == "~/two"
    fields.set_project(project.id)
    assert fields.checkout.text() == ""


def test_the_product_fallback_shows_as_placeholder_not_text(services, project, panel):
    services.document.set_field(services.document.id, "checkout", "~/Code/mono")
    fields = panel._repo_fields
    fields.set_project(project.id)
    assert fields.checkout.text() == ""
    assert "~/Code/mono" in fields.checkout.placeholderText()
    # Absence stays absence: showing the fallback wrote nothing.
    assert MODULE_ID not in project.module_data


def make_fields(services, *, is_git_repo=None, gh_installed=None, gh_signed_in=None):
    """A widget with injected probes — the status facts must not depend on this machine."""
    from dplanner.modules.project_repo.fields import RepoFieldsWidget

    return RepoFieldsWidget(
        services.document,
        services.undo,
        is_git_repo=is_git_repo,
        gh_installed=gh_installed,
        gh_signed_in=gh_signed_in,
    )


def test_the_status_line_reports_git_and_gh_facts(services, project, tmp_path):
    git_answer = {"value": False}
    fields = make_fields(
        services,
        is_git_repo=lambda _path: git_answer["value"],
        gh_installed=lambda: True,
        gh_signed_in=lambda: True,  # Answered from the pre-set cache; never actually run.
    )
    fields.set_project(project.id)
    fields.checkout.setText(str(tmp_path))
    fields.checkout.editingFinished.emit()
    assert "not a git repository" in fields.status.text()
    assert "gh is signed in" in fields.status.text()

    git_answer["value"] = True
    fields.set_project(project.id)
    assert "is a git repository" in fields.status.text()
    fields.dispose()


def test_a_missing_gh_is_said_plainly(services, project, tmp_path):
    fields = make_fields(services, gh_installed=lambda: False)
    fields.set_project(project.id)
    assert "not installed" in fields.status.text()
    fields.dispose()


def test_a_missing_folder_is_said_plainly(services, project, tmp_path):
    fields = make_fields(services)
    fields.set_project(project.id)
    fields.checkout.setText(str(tmp_path / "nowhere"))
    fields.checkout.editingFinished.emit()
    assert "does not exist" in fields.status.text()
    fields.dispose()


def test_an_unwired_probe_says_nothing(services, project, tmp_path):
    """No probe, no claim — an unwired build must not report false facts."""
    fields = make_fields(services)
    fields.set_project(project.id)
    fields.checkout.setText(str(tmp_path))
    fields.checkout.editingFinished.emit()
    assert "git repository" not in fields.status.text()
    assert "gh" not in fields.status.text()
    fields.dispose()
