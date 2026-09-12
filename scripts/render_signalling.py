"""Render the signalling surfaces in the dark and the light theme, to PNG.

    uv run python scripts/render_signalling.py --out docs/screenshots/s10-signalling

Three of them are dialogs and need no library: the quit-time question on the dialog frame,
and the save's progress part-way through and after a failure. The fourth is a real view with
a real rebuild owed — the Time tab over a small synthetic library, with immediate mode off
and a change pushed, which is exactly the 500 ms a person would otherwise spend looking at
a picture of a plan that has since changed.
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

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.domain.commands import SetFieldCommand
from dplanner.modules.sync.exit_dialog import DirtyRepoRow, ExitDialog
from dplanner.modules.sync.save_progress import SaveProgressDialog
from dplanner.modules.sync.service import COMMITTING, PUBLISHING, SAVED
from dplanner.modules.time_estimates.module import TIME_KIND
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

REPOS = [
    DirtyRepoRow(label="~/Code/app-dplanner-planning · 7 files — DPlanner, Adcuris"),
    DirtyRepoRow(label="~/Code/widget · 2 files — Search Rewrite"),
    DirtyRepoRow(label="~/Code/billing · 1 file — Billing"),
]
# Both are *fit* dialogs (DESIGN.md's *Dialogs*): they take their content's height, so the
# render sets only a width, the way a long repository label would.
DIALOG_WIDTH = 620
EXPECTED_S = 12.0  # What the last save of this kind took, for the bar to fill towards.
TAB_SIZE = (1180, 760)
STEPS = 24


def settle(app: QApplication, turns: int = 3) -> None:
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


def render_dialogs(app: QApplication, theme: Theme, out: Path) -> None:
    exit_dialog = ExitDialog(list(REPOS))
    exit_dialog.resize(DIALOG_WIDTH, exit_dialog.sizeHint().height())
    exit_dialog.show()
    save(exit_dialog, out, "exit-dialog", theme, app)
    discard(exit_dialog)

    labels = [row.label for row in REPOS]
    # As it stands part-way through a save on a machine that has saved before: one recorded,
    # one being written, and the bar filled past that third by how long the last one took.
    progress = SaveProgressDialog(labels, expected_seconds=EXPECTED_S)
    progress.resize(DIALOG_WIDTH, progress.sizeHint().height())
    progress.show()
    progress.step(0, SAVED)
    progress.step(1, PUBLISHING)
    progress._started -= EXPECTED_S * 0.55
    progress._redraw()
    save(progress, out, "save-progress", theme, app)
    progress.step(1, COMMITTING)
    progress.stopped("git: the remote refused the push — no upstream for agent/s10")
    save(progress, out, "save-progress-failed", theme, app)
    discard(progress)


def render_updating(app: QApplication, theme: Theme, out: Path, root: Path) -> None:
    """A real tab with a real rebuild owed: the strip says so and the content stays."""
    session = new_session()
    assert session.open_initial(build_library(root / theme.name, steps=STEPS, projects=1))
    services = session.services
    assert services is not None
    services.debounce.set_immediate(False)
    window = session.window
    assert window is not None
    window.resize(*TAB_SIZE)  # The page is a child of the window: sizing it does nothing.
    window.show()
    project = services.document.projects[0]
    activity = services.tabs.open(TIME_KIND, project.id)
    page = activity.widget
    settle(app, 6)
    services.debounce.flush_all()
    settle(app, 6)
    # The person's own change: from here until the burst settles the page shows the old
    # answer, and the strip is what says so.
    services.undo.push(SetFieldCommand(project.steps[0].id, "title", "Renamed just now"))
    save(page, out, "time-updating", theme, app)
    services.debounce.flush_all()
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s10-signalling"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    configure_application(app)
    with tempfile.TemporaryDirectory(prefix="dplanner-signalling-") as tmp:
        for theme in (DARK, LIGHT):
            apply_theme(app, theme)
            render_dialogs(app, theme, args.out)
            render_updating(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
