"""Reporting in the window: the exports run as tasks, the preview opens the page, and the
report site is exported into a folder the person picks.

The decisions pinned here: an export builds on the GUI thread and writes on a worker the
task centre shows; the site export writes every project of the focused project's plan
repository and starts at its reporting location; Save never writes a report.
"""

import subprocess
import time
from pathlib import Path

import pytest

from dplanner.cli.report import website
from dplanner.core.storage.locations import init_repo
from dplanner.core.storage.pointer import POINTER_FILE
from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri


def wait_for(app, predicate, timeout=10.0):
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, "the task never finished"
        app.processEvents()
        time.sleep(0.01)


def select_project(services, project):
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )


def sync_service(services):
    module = next(m for m in services.modules if m.id == "sync")
    assert module.service is not None
    return module.service


def committed_paths(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.split()


@pytest.fixture
def project(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Interview the pilots")
    services.undo.push(AddNodeCommand(project.id, step))
    services.undo.push(SetModuleDataCommand(step.id, "estimation", {"days": 2.0}))
    return project


def _save_dialog(monkeypatch, target: Path) -> None:
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(target), ""))
    )


@pytest.mark.parametrize(
    ("action", "suffix", "head"),
    [("report.html", ".html", b"<!doctype html>"), ("report.xlsx", ".xlsx", b"PK")],
)
def test_an_export_writes_the_file_through_a_task(
    qapp, services, project, tmp_path, monkeypatch, action, suffix, head
):
    target = tmp_path / f"plan{suffix}"
    _save_dialog(monkeypatch, target)
    select_project(services, project)
    services.actions.run(action, services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())
    assert target.read_bytes().startswith(head)
    assert any(task.label == "Writing report" for task in services.tasks.finished())
    spec = services.actions.spec(action)
    assert (spec.menu, spec.group, spec.submenu) == ("File", "export", "Export")


def test_the_pdf_export_prints_the_report(qapp, services, project, tmp_path, monkeypatch):
    target = tmp_path / "plan.pdf"
    _save_dialog(monkeypatch, target)
    select_project(services, project)
    services.actions.run("report.pdf", services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())
    data = target.read_bytes()
    assert data.startswith(b"%PDF-") and len(data) > 2000


def test_a_forced_suffix_and_a_cancelled_dialog(qapp, services, project, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    _save_dialog(monkeypatch, tmp_path / "plan.txt")
    select_project(services, project)
    services.actions.run("report.html", services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())
    assert (tmp_path / "plan.html").is_file()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: ("", "")))
    services.actions.run("report.xlsx", services.context.current())
    assert not services.tasks.active()


def test_the_preview_opens_the_page_it_wrote(qapp, services, project, monkeypatch):
    from PySide6.QtGui import QDesktopServices

    opened: list[str] = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toLocalFile()))
    )
    select_project(services, project)
    services.actions.run("report.preview", services.context.current())
    wait_for(qapp, lambda: bool(opened))
    assert Path(opened[0]).read_text(encoding="utf-8").startswith("<!doctype html>")
    spec = services.actions.spec("report.preview")
    assert (spec.menu, spec.group) == ("Go", "survey")


def test_the_exports_need_a_project(services):
    services.context.clear_scope(SCOPE_SELECTION)
    for action in ("report.html", "report.pdf", "report.xlsx", "report.site", "report.preview"):
        assert not services.actions.spec(action).state(services.context.current()).enabled


def test_save_writes_no_report_site(qapp, services, project, library_repo):
    """Generated pages committed by every Save collide between people sharing a plan
    repository, so Save records the plan and nothing else."""
    services.autosave.flush_now()
    select_project(services, project)
    services.actions.run("sync.save", services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())
    assert not (library_repo / website.REPORTS_DIR).exists()
    paths = committed_paths(library_repo)
    assert any(path.startswith("discovery/") for path in paths)
    assert all(path.startswith(("discovery/", POINTER_FILE)) for path in paths)
    service = sync_service(services)
    service.refresh()
    assert not service.dirty_groups()


def _folder_dialog(monkeypatch, folder: Path | None) -> list[str]:
    """Answers the folder picker with ``folder`` (None: cancelled); returns where it opened."""
    from PySide6.QtWidgets import QFileDialog

    opened: list[str] = []

    def pick(_parent, _title, start):
        opened.append(start)
        return "" if folder is None else str(folder)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(pick))
    return opened


def test_the_site_export_writes_the_repositorys_projects_into_the_picked_folder(
    qapp, services, project, make_project, tmp_path, monkeypatch
):
    from dplanner.domain.seed import seed_project

    make_project("Delivery")
    elsewhere = init_repo(tmp_path / "elsewhere")
    services.document.add_child(
        services.document.id, services.repo.attach(seed_project(elsewhere / "aside", "Aside"))
    )
    folder = tmp_path / "site"
    folder.mkdir()
    opened = _folder_dialog(monkeypatch, folder)
    select_project(services, project)
    services.actions.run("report.site", services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())
    assert opened == [str(Path.home())]
    assert (folder / "index.html").is_file()
    assert (folder / "discovery" / "index.html").is_file()
    assert (folder / "delivery" / "summary.js").is_file()
    assert not (folder / "aside").exists()  # Another plan repository's project.
    assert any(task.label == "Writing report site" for task in services.tasks.finished())
    spec = services.actions.spec("report.site")
    assert (spec.menu, spec.group, spec.submenu) == ("File", "export", "Export")


def test_a_cancelled_site_export_writes_nothing(qapp, services, project, monkeypatch):
    _folder_dialog(monkeypatch, None)
    select_project(services, project)
    services.actions.run("report.site", services.context.current())
    assert not services.tasks.active()


def test_the_milestones_csv_writes_the_report_table(services, project, tmp_path, monkeypatch):
    from dplanner.planning.milestone import write as milestone

    services.undo.push(SetModuleDataCommand(project.steps[0].id, "step_milestone", milestone("v1")))
    target = tmp_path / "milestones.csv"
    _save_dialog(monkeypatch, target)
    select_project(services, project)
    services.actions.run("time.export", services.context.current())
    lines = target.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0].startswith("Milestone,Set date,Lands,Days,Steps,Done")
    assert lines[1].startswith("v1,")
    spec = services.actions.spec("time.export")
    assert (spec.menu, spec.group, spec.submenu) == ("File", "export", "Export")


@pytest.mark.parametrize(("kind", "strip"), [("order", "toolbar"), ("time", "controls")])
def test_the_tabs_export_button_renders_the_export_submenu(services, project, kind, strip):
    activity = services.tabs.open(kind, project.id)
    select_project(services, project)
    menu = getattr(activity, strip).menu_for("report.html")
    assert menu is not None
    labels = [
        action.text().replace("&", "") for action in menu.actions() if not action.isSeparator()
    ]
    assert "Order List (CSV)…" in labels and "Milestones (CSV)…" in labels
    assert "Plan Report (HTML)…" in labels and "Plan Report (PDF)…" in labels
    assert "Plan Tables (Excel)…" in labels


# -- the reporting location ---------------------------------------------------------------------


def reporting_row(url: str, path: str = "reports/search"):
    from dplanner.domain.locations import Location

    return Location("l9", "reporting", url, path=path)


def test_the_site_export_starts_at_the_reporting_location(
    qapp, services, project, tmp_path, monkeypatch
):
    from dplanner.domain.commands import SetFieldCommand

    reports = init_repo(tmp_path / "reports-repo")
    url = "https://github.com/acme/reports"
    services.undo.push(SetFieldCommand(project.id, "locations", (reporting_row(url),)))
    services.repo.set_checkout(url, reports)
    opened = _folder_dialog(monkeypatch, None)
    select_project(services, project)
    services.actions.run("report.site", services.context.current())
    assert opened == [str(reports / "reports" / "search")]


def test_the_terminal_and_the_tests_export_land_at_the_reporting_location_too(
    services, project, tmp_path, monkeypatch
):
    """The site export and the Tests tab's export offer the same place: where colleagues
    read."""
    from dplanner.domain.commands import SetFieldCommand

    reports = init_repo(tmp_path / "reports-repo")
    url = "https://github.com/acme/reports"
    services.undo.push(SetFieldCommand(project.id, "locations", (reporting_row(url),)))
    services.repo.set_checkout(url, reports)
    module = next(m for m in services.modules if m.id == "testing")
    assert module._deps.reporting_dir(project.id) == reports / "reports" / "search"
    services.repo.set_checkout(url, None)
    assert module._deps.reporting_dir(project.id) is None  # Not here: the home directory.
