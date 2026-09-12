"""Reporting in the window: the exports run as tasks, the preview opens the page, and Save
writes the plan repository's site into the same commit as the plan.

The decisions pinned here: an export builds on the GUI thread and writes on a worker the
task centre shows; Save publishes by default and records ``reports/`` with the plan; the
switch turns it off; a publication that fails never costs the save.
"""

import subprocess
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QObject
from PySide6.QtCore import Signal as QtSignal
from PySide6.QtWidgets import QPushButton

from dplanner.cli.report import website
from dplanner.domain.commands import AddNodeCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.signalling import Spinner
from dplanner.framework.user_config import set_global
from dplanner.modules.reporting.settings_page import MODULE_ID, PUBLISH_KEY, build_page


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


def reporting_module(services):
    return next(m for m in services.modules if m.id == MODULE_ID)


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
    assert (spec.menu, spec.group) == ("Project", "open")


def test_the_exports_need_a_project(services):
    services.context.clear_scope(SCOPE_SELECTION)
    for action in ("report.html", "report.pdf", "report.xlsx", "report.preview"):
        assert not services.actions.spec(action).state(services.context.current()).enabled


def test_save_publishes_the_site_beside_the_plan(qapp, services, project, library_repo):
    services.autosave.flush_now()
    select_project(services, project)
    services.actions.run("sync.save", services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())
    paths = committed_paths(library_repo)
    assert any(path.startswith("discovery/") for path in paths)
    assert f"{website.REPORTS_DIR}/discovery/index.html" in paths
    assert f"{website.REPORTS_DIR}/discovery/summary.js" in paths
    assert f"{website.REPORTS_DIR}/index.html" in paths
    page = (library_repo / website.REPORTS_DIR / "discovery" / "index.html").read_text()
    assert "Discovery" in page
    # The site is not the plan: the repository reads clean afterwards.
    service = sync_service(services)
    service.refresh()
    assert not service.dirty_groups()


def test_the_switch_turns_publishing_off(qapp, services, project, library_repo):
    set_global(MODULE_ID, PUBLISH_KEY, False)
    services.autosave.flush_now()
    select_project(services, project)
    services.actions.run("sync.save", services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())
    assert not (library_repo / website.REPORTS_DIR).exists()
    assert all(path.startswith("discovery/") for path in committed_paths(library_repo))


def test_a_failing_publication_never_costs_the_save(
    qapp, services, project, library_repo, monkeypatch
):
    def refuse(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(website, "write", refuse)
    notices: list[str] = []
    service = sync_service(services)
    service.notice.connect(notices.append)
    services.autosave.flush_now()
    select_project(services, project)
    services.actions.run("sync.save", services.context.current())
    wait_for(qapp, lambda: not services.tasks.active())
    assert any(path.startswith("discovery/") for path in committed_paths(library_repo))
    assert notices and notices[-1].startswith("Saved") and "reports not written" in notices[-1]


def test_write_now_writes_every_repository(qapp, services, project, library_repo):
    reporting_module(services).write_site()
    wait_for(qapp, lambda: not services.tasks.active())
    assert (library_repo / website.REPORTS_DIR / "discovery" / "index.html").is_file()
    assert (library_repo / website.REPORTS_DIR / "index.html").is_file()


def test_the_milestones_csv_writes_the_report_table(services, project, tmp_path, monkeypatch):
    from dplanner.modules.step_milestone.aspect import write as milestone

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


@pytest.mark.parametrize("kind", ["order", "time"])
def test_the_tabs_export_button_renders_the_export_submenu(services, project, kind):
    activity = services.tabs.open(kind, project.id)
    select_project(services, project)
    menu = activity.toolbar.menu_for("report.html")
    assert menu is not None
    labels = [
        action.text().replace("&", "") for action in menu.actions() if not action.isSeparator()
    ]
    assert "Order List (CSV)…" in labels and "Milestones (CSV)…" in labels
    assert "Plan Report (HTML)…" in labels and "Plan Report (PDF)…" in labels
    assert "Plan Tables (Excel)…" in labels


class QtSignalHost(QObject):
    """Stands in for the reporting module's runner: the one signal the page listens to."""

    changed = QtSignal(bool)


def test_write_now_turns_its_own_glyph_while_a_report_is_being_written(app):
    """DESIGN.md's *Signalling*, *Working*: the button whose verb started the work says so
    in the glyph slot it already had, so nothing on the page moves."""
    busy = QtSignalHost()
    page = build_page(None, write_now=lambda: None, busy_changed=busy.changed)
    try:
        button = page.findChild(QPushButton, "writeSiteNow")
        spinner = page.findChild(Spinner)
        assert button is not None and spinner is not None
        assert not button.icon().isNull()  # A spinner refuses a button with no idle glyph.
        idle = button.icon().cacheKey()
        busy.changed.emit(True)
        assert spinner.is_spinning() and button.icon().cacheKey() != idle
        busy.changed.emit(False)
        assert not spinner.is_spinning() and button.icon().cacheKey() == idle
    finally:
        page.deleteLater()
