"""Render the surfaces the tables-and-browsers pass brings up, in the dark and the light theme.

    uv run python scripts/render_tables_and_browsers.py
    uv run python scripts/render_tables_and_browsers.py --prefix before-  # on the parent commit

Every surface is the real one, built by a whole application over a synthetic library, so
nothing here hand-wires a view the window would build differently: the Tests tab and the
roll call of every project's tests, the Coverage tab, the Assets tab over pictures attached
to steps, the Implementation notes tab, the bulk Estimates tab, the Time tab, the task
browser over tasks in each state, the Agents browser over a live, a finished and a failed
run, and the command palette open, filtered and with nothing to show. A tab is rendered at
its own size — lifted off the tab host for the grab — and again with a row picked, which is
where a table's edge over the quiet ground is read.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QAbstractItemView, QApplication, QWidget
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.domain.assets import attach
from dplanner.framework.palette import CommandPalette
from dplanner.framework.services import AppServices
from dplanner.modules.coverage.activity import COVERAGE_KIND
from dplanner.modules.estimation.bulk import ESTIMATE_KIND
from dplanner.modules.notes.activity import NOTES_KIND
from dplanner.modules.project_assets.activity import ASSETS_KIND
from dplanner.modules.step_agent_run.module import StepAgentRunModule
from dplanner.modules.step_description.aspect import MODULE_ID as DESCRIPTION_ID
from dplanner.modules.taskcenter.module import TaskCenterModule
from dplanner.modules.testing.activity import ALL_TESTS_KIND, TESTS_KIND
from dplanner.modules.time_estimates.module import TIME_KIND
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

TAB_SIZE = (1180, 720)
BROWSER_SIZE = (560, 400)
PALETTE_HEIGHT = 420
STEPS = 48  # Three milestones, a few dozen tests, a handful of notes.
PICTURES = ("#4c6ef5", "#2f9e44", "#e8590c", "#ae3ec9")


def settle(app: QApplication, turns: int = 6) -> None:
    for _ in range(turns):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def discard(widget: QWidget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def picture(color: str, words: str) -> bytes:
    image = QImage(240, 150, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    painter = QPainter(image)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, words)
    painter.end()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def attach_pictures(services: AppServices, steps: list) -> None:
    """Three pictures a description links and one nobody does, so the sweep has work."""
    library = services.document
    for index, (step, color) in enumerate(zip(steps, PICTURES, strict=False)):
        area = services.repo.files(step.id, DESCRIPTION_ID)
        name = attach(area, picture(color, f"figure {index + 1}"), f"figure-{index + 1}.png")
        if index < len(PICTURES) - 1:
            text = library.text(step.id, DESCRIPTION_ID)
            library.set_text(step.id, DESCRIPTION_ID, f"{text}\n![figure]({name})\n")


def pick_a_row(widget: QWidget) -> bool:
    """Pick the second selectable row of the widest roster on the page, if it has one."""
    views = [
        view
        for view in widget.findChildren(QAbstractItemView)
        if view.isVisible() and view.model() is not None and view.model().rowCount() > 2
    ]
    if not views:
        return False
    view = max(views, key=lambda candidate: candidate.width() * candidate.height())
    model = view.model()
    rows = [
        row
        for row in range(model.rowCount())
        if model.flags(model.index(row, 0)) & Qt.ItemFlag.ItemIsSelectable
    ]
    if len(rows) < 2:
        return False
    view.setCurrentIndex(model.index(rows[1], 0))
    return True


def render_tab(activity, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    # Off the tab host, so the render is the surface's own size and not what the window's
    # panels leave it.
    widget = activity.widget
    host = widget.parentWidget()
    widget.setParent(None)
    widget.resize(*TAB_SIZE)
    widget.show()
    settle(app)
    save(widget, out, name, theme, app)
    if pick_a_row(widget):
        save(widget, out, f"{name}-picked", theme, app)
    widget.hide()
    widget.setParent(host)


def render_tasks(services: AppServices, out: Path, prefix: str, theme: Theme, app) -> None:
    tasks = services.tasks
    fetching = tasks.start(
        "Fetching 12 Confluence pages",
        cancellable=True,
        cancel_prompt="Stop fetching? The pages already fetched are kept.",
    )
    tasks.set_progress(fetching, 0.4)
    tasks.start("Cloning app-dplanner-planning")
    written = tasks.start("Writing the report", keep_finished=True)
    tasks.finish(written)
    failed = tasks.start("Checking the GitHub CLI", keep_finished=True)
    tasks.finish(failed, error="gh: not logged in to github.com")
    centre = next(m for m in services.modules if isinstance(m, TaskCenterModule))
    services.actions.run("taskcenter.show_tasks", services.context.current())
    browser = centre.browser
    browser.resize(*BROWSER_SIZE)
    save(browser, out, f"{prefix}tasks", theme, app)
    browser.hide()


def render_agents(
    services: AppServices, steps: list, root: Path, out: Path, prefix: str, theme: Theme, app
) -> None:
    runs = next(m for m in services.modules if isinstance(m, StepAgentRunModule))
    for index, (step, ending) in enumerate(zip(steps, ("", "0\n", "3\n"), strict=True)):
        directory = root / f"run-{theme.name}-{index}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "shell").write_text("tty=/dev/pts/4\n")
        runs.track(step.id, str(directory / "shell"), str(directory / "exit"))
        if ending:
            (directory / "exit").write_text(ending)
    runs.check()
    runs._open_browser()
    browser = runs._browser
    assert browser is not None
    browser.resize(*BROWSER_SIZE)
    save(browser, out, f"{prefix}agents", theme, app)
    browser.hide()


def render_palette(services: AppServices, out: Path, prefix: str, theme: Theme, app) -> None:
    window = services.window
    palette = CommandPalette(services.actions, services.context, window)
    palette.resize(palette.width(), PALETTE_HEIGHT)
    palette.show()
    save(palette, out, f"{prefix}palette", theme, app)
    palette.field.setText("mark")
    save(palette, out, f"{prefix}palette-filtered", theme, app)
    palette.field.setText("zqxj")
    save(palette, out, f"{prefix}palette-nothing", theme, app)
    palette.hide()
    discard(palette)


def render(app: QApplication, theme: Theme, out: Path, root: Path, prefix: str) -> None:
    apply_theme(app, theme)
    session = new_session()
    assert session.open_initial(build_library(root / theme.name, steps=STEPS, projects=1))
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    window = session.window
    assert window is not None
    window.resize(*TAB_SIZE)
    window.show()
    project = services.document.projects[0]
    steps = list(project.steps)
    attach_pictures(services, steps[2:6])
    settle(app)

    for name, kind, target in (
        ("tests", TESTS_KIND, project.id),
        ("all-tests", ALL_TESTS_KIND, None),
        ("coverage", COVERAGE_KIND, project.id),
        ("assets", ASSETS_KIND, project.id),
        ("notes", NOTES_KIND, project.id),
        ("estimates", ESTIMATE_KIND, project.id),
        ("time", TIME_KIND, project.id),
    ):
        activity = services.tabs.open(kind, target)
        services.debounce.flush_all()
        render_tab(activity, out, f"{prefix}{name}", theme, app)

    render_tasks(services, out, prefix, theme, app)
    render_agents(services, steps[10:13], root, out, prefix, theme, app)
    render_palette(services, out, prefix, theme, app)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--out", type=Path, default=Path("docs/screenshots/s15-tables-and-browsers")
    )
    parser.add_argument("--prefix", default="", help="before- for the renders of the old code")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    with tempfile.TemporaryDirectory(prefix="dplanner-s15-") as tmp:
        # Per-user settings into the throwaway directory, before anything reads them: the
        # Agents browser lists the runs this machine remembers, and tracking a pretend run
        # writes one — neither the developer's runs nor these renders' belong in the other.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, f"{tmp}/settings")
        configure_application(app)
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp), args.prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
