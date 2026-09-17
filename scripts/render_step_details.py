"""Render the step detail dialog in the dark and the light theme, to PNG.

    uv run python scripts/render_step_details.py --out docs/screenshots/s6-step-details

The surfaces S6 reworked: the aspect bar's toggles on the left and the template it amounts
to on the right, the Details tab stacking from the top whatever is turned off, and the
dialog on ``DialogFrame`` with one Close in its footer. The panel has one host — the dialog
``steps.details`` opens — so every image here is of that, reached through the verb rather
than hand-wired, over a whole application built on a throwaway library and torn down per
theme.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.app import new_session
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.model import Step
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.context import (
    SCOPE_SELECTION,
    ContextNode,
    selection_uri,
)
from dplanner.modules.step_properties.dialog import StepDetailsDialog
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

DIALOG_SIZE = (900, 760)


def settle(app: QApplication) -> None:
    for _ in range(3):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def discard(widget: QWidget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def render(app: QApplication, theme: Theme, out: Path, workspace: Path) -> None:
    apply_theme(app, theme)
    library_file = workspace / f"library-{theme.name}.json"
    create_library(library_file)
    init_repo(workspace)
    session = new_session()
    assert session.open_initial(library_file)
    services = session.services
    assert services is not None
    services.debounce.set_immediate(True)

    # A project is a directory, so it is seeded and attached exactly as the window does it.
    directory = seed_project(workspace / f"discovery-{theme.name}", "Discovery")
    project = services.repo.attach(directory)
    services.document.add_child(services.document.id, project)
    step = Step(title="Build the quick-reg modal")
    AddNodeCommand(project.id, step).redo(services.document)
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))
    settle(app)

    # Through the verb that opens it, so nothing here re-wires what the window builds.
    # exec() would block and the verb disposes on the way out, so both stand aside.
    opened: list[StepDetailsDialog] = []
    real_exec, real_dispose = StepDetailsDialog.exec, StepDetailsDialog.dispose
    StepDetailsDialog.exec = lambda self: opened.append(self)  # type: ignore[method-assign]
    StepDetailsDialog.dispose = lambda self: None  # type: ignore[method-assign]
    try:
        services.actions.run("steps.details", services.context.current())
    finally:
        StepDetailsDialog.exec = real_exec  # type: ignore[method-assign]
        StepDetailsDialog.dispose = real_dispose  # type: ignore[method-assign]
    (dialog,) = opened
    dialog.resize(*DIALOG_SIZE)
    dialog.show()
    settle(app)
    save(dialog, out, "dialog", theme, app)

    # The bar's own dropdown: what the step could be, with what it is ticked.
    bar = dialog.panel.bar
    # popup(), never showMenu(): the latter runs its own event loop and never returns here.
    bar.face.menu().popup(dialog.mapToGlobal(bar.face.pos()))
    settle(app)
    save(bar.face.menu(), out, "templates", theme, app)
    bar.face.menu().hide()

    # Every aspect off — the shape this step exists to fix: the blocks stay at the top.
    for action_id in ("estimate.toggle", "description.toggle"):
        action = bar.action(action_id)
        if action.isChecked():
            action.trigger()
    settle(app)
    save(dialog, out, "dialog-bare", theme, app)

    real_dispose(dialog)
    discard(dialog)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the PNGs")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    # The throwaway library lives outside the output directory: what lands there is images.
    with TemporaryDirectory(prefix="dplanner-render-") as tmp:
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
