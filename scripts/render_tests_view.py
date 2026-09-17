"""Render the Tests view's surfaces, in the dark and the light theme.

    uv run python scripts/render_tests_view.py

Every surface is the real one, built by a whole application over
``scripts/synthetic_library.py``'s plan, so nothing here hand-wires a view the window would
build differently: the Tests tab filed by category, the same tab with a category folded
shut, the Test panel a run is worked down from, the preview a reference in a body opens,
and the category editor.
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

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication, QWidget
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.framework.services import AppServices
from dplanner.modules.testing.activity import TESTS_KIND
from dplanner.modules.testing.aspect import project_tests
from dplanner.modules.testing.categories_dialog import CategoriesDialog
from dplanner.modules.testing.preview_dialog import PREVIEW_SIZE, TestPreview
from dplanner.modules.testing.references import mentions
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

TAB_SIZE = (1520, 640)
DIALOG_SIZE = (560, 460)
WINDOW_SIZE = (1440, 760)
STEPS = 48


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


def lifted(activity: object) -> tuple[QWidget, QWidget | None]:
    """A tab off its host, at its own size — not what the window's panels leave it."""
    widget = activity.widget  # type: ignore[attr-defined]
    host = widget.parentWidget()
    widget.setParent(None)
    widget.resize(*TAB_SIZE)
    widget.show()
    return widget, host


def render_tab(services: AppServices, out: Path, theme: Theme, app: QApplication) -> None:
    project = services.document.projects[0]
    activity = services.tabs.open(TESTS_KIND, project.id)
    services.debounce.flush_all()
    widget, host = lifted(activity)
    save(widget, out, "tests-filed", theme, app)

    # One category shut: the reading the folding is for — a dozen lines, and you open the
    # one you are working in.
    table = activity.page.table
    first = next((row for row in range(table.rowCount()) if table.group_at(row)), None)
    if first is not None:
        table.toggle_group(table.group_at(first))
        save(widget, out, "tests-folded", theme, app)
        table.toggle_group(table.group_at(first))
    widget.hide()
    widget.setParent(host)


def render_panel(services: AppServices, out: Path, theme: Theme, app: QApplication) -> None:
    """The Test panel beside the roster, over the first test the tab is showing — as a
    double-click leaves it."""
    project = services.document.projects[0]
    activity = services.tabs.open(TESTS_KIND, project.id)
    services.debounce.flush_all()
    # The first test that has a body: the panel's whole point is the rendered one, and the
    # synthetic plan gives only half its tests prose.
    wanted = next(
        (
            test.id
            for _step, test in project_tests(activity._project())
            if test.body and test.id in set(activity.ordered_tests())
        ),
        None,
    )
    if wanted is None:
        return
    # The tab's own pick feeds its panel, and the verb stands the panel — one gesture.
    activity.pick_test(wanted)
    services.actions.run("test.details", services.context.current())
    settle(app)
    save(activity.page.side_panel.frame, out, "test-panel", theme, app)


def render_preview(services: AppServices, out: Path, theme: Theme, app: QApplication) -> None:
    """The preview a reference opens — over the test whose body points at another."""
    project = services.document.projects[0]
    wanted = next((test.id for _step, test in project_tests(project) if mentions(test.body)), None)
    if wanted is None:
        return
    dialog = TestPreview(services.document, project.id, wanted, None)
    dialog.resize(*PREVIEW_SIZE)
    dialog.show()
    save(dialog, out, "test-preview", theme, app)
    dialog.reject()
    discard(dialog)


def render_editor(services: AppServices, out: Path, theme: Theme, app: QApplication) -> None:
    project = services.document.projects[0]
    dialog = CategoriesDialog(services.document, services.undo, project.id)
    dialog.resize(*DIALOG_SIZE)
    dialog.show()
    save(dialog, out, "category-editor", theme, app)
    dialog.reject()
    discard(dialog)


def render(app: QApplication, theme: Theme, out: Path, root: Path) -> None:
    apply_theme(app, theme)
    session = new_session()
    assert session.open_initial(build_library(root / theme.name, steps=STEPS, projects=1))
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)
    window = session.window
    assert window is not None
    window.resize(*WINDOW_SIZE)
    window.show()
    settle(app)

    render_tab(services, out, theme, app)
    render_panel(services, out, theme, app)
    render_preview(services, out, theme, app)
    render_editor(services, out, theme, app)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s16-tests-view"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    with tempfile.TemporaryDirectory(prefix="dplanner-tests-view-") as tmp:
        # Per-user settings into the throwaway directory, before anything reads them: a
        # panel's visibility is remembered per user, and these renders' answer is not the
        # developer's.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, f"{tmp}/settings")
        configure_application(app)
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
