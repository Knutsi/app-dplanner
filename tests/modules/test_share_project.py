"""Sharing a project: the verb's refusals, and what the dialog hands over.

The round trip is the point, so it is the last test here: what *Share Project…* writes is
read back by the same domain reader the *Open Project…* wizard uses, and neither surface
is allowed to be the only one that understands it.
"""

import subprocess

import pytest
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtWidgets import QFileDialog

from dplanner.core.storage.locations import init_repo
from dplanner.domain.project_link import SUFFIX, link_for, read
from dplanner.domain.seed import seed_project
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.projects import module as projects_module
from dplanner.modules.projects.share_dialog import QUIET, ShareProjectDialog

ORIGIN = "https://github.com/acme/plans"
CODE = "https://github.com/acme/widget"


def module(services):
    return next(m for m in services.modules if m.id == "projects")


@pytest.fixture
def notices(monkeypatch):
    """Every notice the module shows, instead of a modal nobody would dismiss."""
    shown = []
    monkeypatch.setattr(
        projects_module, "notice", lambda _parent, title, text: shown.append((title, text))
    )
    return shown


@pytest.fixture
def dialogs(monkeypatch):
    """Stands in for the Share dialog at the name the module reads; records the link."""
    seen = []

    class Fake:
        def __init__(self, link, _parent=None):
            seen.append(link)

        def exec(self):
            return 0

        def deleteLater(self):  # noqa: N802 - Qt's name
            pass

    monkeypatch.setattr(projects_module, "ShareProjectDialog", Fake)
    return seen


@pytest.fixture
def published(services, tmp_path):
    """A project in a plan repository that has a remote, planning code that has one too."""
    root = init_repo(tmp_path / "plans")
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", ORIGIN], check=True)
    directory = seed_project(root / "search", "Search", summary="Replace the index")
    project = module(services)._deps.connect_project(directory, None)
    project.repository = CODE
    return project


# -- the verb --------------------------------------------------------------------------------


def test_sharing_hands_the_dialog_both_repositories_and_the_folder_in_between(
    services, published, dialogs
):
    module(services).share_project(published.id)
    (link,) = dialogs
    assert link.plan_remote == ORIGIN
    assert link.plan_path == "search"
    assert link.code_remote == CODE
    assert (link.title, link.summary) == ("Search", "Replace the index")
    assert link.project_id == published.id


def test_a_plan_nobody_else_can_clone_is_refused_with_what_to_do(
    services, library_repo, make_project, notices, dialogs
):
    project = make_project("Discovery")  # A local repository: no remote to clone from.
    module(services).share_project(project.id)
    assert dialogs == []
    (title, text) = notices[0]
    assert title == "Share Project"
    assert "no remote" in text and "publish it to GitHub" in text


def test_the_verb_is_greyed_until_a_project_is_focused(services, published):
    """Disabled, never hidden: the greyed entry is what teaches the precondition."""
    state = services.actions.spec("projects.share").state
    assert state is not None
    assert not state(services.context.current()).enabled
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", published.id)),)
    )
    assert state(services.context.current()).enabled


# -- the dialog ------------------------------------------------------------------------------


def share_dialog(services, published):
    deps = module(services)._deps
    link = link_for(
        published, deps.repos.project_dir(published.id), deps.repos.facts_of(published.id)
    )
    return ShareProjectDialog(link, services.window)


def test_the_dialog_names_the_project_in_its_title_and_shows_the_link_to_copy(services, published):
    dialog = share_dialog(services, published)
    assert dialog.windowTitle() == "Share “Search”"  # The frame prints no heading of its own.
    assert dialog.link_edit.text().startswith("dplanner://project?")
    assert dialog.link_edit.isReadOnly()
    assert dialog.copy_button.text() == "Copy Link"
    dialog.deleteLater()


def test_the_sentence_over_the_link_says_what_it_sets_up_and_that_it_grants_nothing(
    services, published
):
    dialog = share_dialog(services, published)
    said = dialog.about.text()
    assert "“Search” from acme/plans · search" in said
    assert "acme/widget as its code" in said
    assert "carries no access" in said
    dialog.deleteLater()


def test_the_code_is_a_square_of_modules_with_the_quiet_zone_around_it(services, published):
    dialog = share_dialog(services, published)
    code = dialog.code
    across = len(code.matrix) + 2 * QUIET
    assert code.width() == code.height() == across * code.module
    assert all(len(row) == len(code.matrix) for row in code.matrix)  # Square, as a QR is.
    dialog.deleteLater()


def test_what_the_code_paints_is_the_matrix_it_was_given(services, published):
    """Rendered and read back, module by module: a QR nobody can scan is worse than none,
    and the painter is the half segno cannot vouch for."""
    dialog = share_dialog(services, published)
    code = dialog.code
    image = QImage(code.size(), QImage.Format.Format_RGB32)
    code.render(image)
    size = code.module
    for row, modules in enumerate(code.matrix):
        for column, on in enumerate(modules):
            # The middle of the module, so a rounding error at an edge cannot pass.
            x = (column + QUIET) * size + size // 2
            y = (row + QUIET) * size + size // 2
            dark = QColor(image.pixel(x, y)).lightness() < 128
            assert dark == bool(on), f"module {row},{column}"
    corner = QColor(image.pixel(size // 2, size // 2))  # Inside the quiet zone.
    assert corner.lightness() > 200  # Light whatever the theme: a camera reads this.
    dialog.deleteLater()


def test_copy_link_puts_the_link_on_the_clipboard_and_says_so(services, published):
    dialog = share_dialog(services, published)
    dialog.copy_button.click()
    assert QGuiApplication.clipboard().text() == dialog.text
    assert dialog.status.tone() == "ok" and "copied" in dialog.status.words()
    QGuiApplication.clipboard().clear()  # A headless run leaves the clipboard as it found it.
    dialog.deleteLater()


def test_saving_writes_a_dlink_file_the_wizard_can_read_back(
    services, published, tmp_path, monkeypatch
):
    dialog = share_dialog(services, published)
    target = tmp_path / "search"  # No suffix: the dialog adds the one it writes.
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    dialog.save_button.click()
    written = target.with_suffix(SUFFIX)
    assert written.is_file() and "Saved to" in dialog.status.words()
    assert read(str(written)) == dialog.link
    assert read(dialog.text) == dialog.link  # Both ways round trip to the same link.
    dialog.deleteLater()
