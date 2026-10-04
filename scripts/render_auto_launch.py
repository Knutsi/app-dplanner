"""Render what the window says when it launches what became due, in the dark and the light theme.

    uv run python scripts/render_auto_launch.py --out docs/screenshots/f14-auto-launch

A whole application over a synthetic library, with *When a step becomes due* on and the
terminal faked, so nothing opens. Three agents' steps reach review and their collector is
launched on its own into Claude's plan mode: the window's top with the notice that says it
waits for a person, and the Step statuses tab with it under *Waits for you*. Before that,
while another window holds the library's lock, the *Agent profiles* page, whose switch says
that window launches.
"""

import argparse
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication, QWidget
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.core.storage.pointer import remove_from_index
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Step
from dplanner.framework.user_config import set_global
from dplanner.modules.auto_progress.aspect import MODULE_ID as AUTO_PROGRESS_ID
from dplanner.modules.auto_progress.aspect import write as write_flags
from dplanner.modules.progression.module import PROGRESSION_KIND
from dplanner.modules.settings.dialog import DIALOG_SIZE as SETTINGS_SIZE
from dplanner.modules.settings.module import SettingsModule
from dplanner.modules.step_agent_instruction import launcher
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.auto_launch import LaunchLocks
from dplanner.modules.step_agent_instruction.settings_page import AUTO_LAUNCH_KEY
from dplanner.planning.status import MODULE_ID as STATUS_ID
from dplanner.planning.status import write as write_status
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

WINDOW_SIZE = (1180, 760)
BELOW_BAR = 44  # How much of the tabs under the notice the grab keeps, for context.
STEPS = 24
SOURCES = (
    "Stacks: drag to reorder, and the cards make way",
    "Edges: finished lines recede, the pick lights its path",
    "Wave view in motion: the glide and a drag within a column",
)
COLLECTOR = "The round lands: its three branches merged and reviewed as one"


def settle(app: QApplication, turns: int = 6) -> None:
    for _ in range(turns):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def save_top(window: QWidget, bar: QWidget, out: Path, name: str, theme: Theme, app) -> None:
    """The window from its menu bar to just under the notice — where the notice is read."""
    settle(app)
    bottom = bar.mapTo(window, bar.rect().bottomLeft()).y() + BELOW_BAR
    path = out / f"{name}-{theme.name}.png"
    window.grab(QRect(0, 0, window.width(), bottom)).save(str(path), "PNG")
    print(path)


def render(app: QApplication, theme: Theme, out: Path, root: Path) -> None:
    apply_theme(app, theme)
    set_global(AGENT_ID, AUTO_LAUNCH_KEY, False)  # Each theme's window starts with it off.
    locks = root / f"locks-{theme.name}"
    session = new_session(launch_locks=locks)
    library_file = build_library(root / theme.name, steps=STEPS, projects=1)
    # Out of its repository's index: a plan beside its code, so an agent has somewhere to work.
    for directory in (root / theme.name / "plans").iterdir():
        if (directory / "project.dproj").is_file():
            remove_from_index(directory)
    assert session.open_initial(library_file)
    services = session.services
    window = session.window
    assert services is not None and window is not None
    services.debounce.set_immediate(True)
    window.resize(*WINDOW_SIZE)
    window.show()
    library = services.document
    project = library.projects[0]
    today = date.today()

    def agent_step(title: str, status: str) -> Step:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        library.set_text(step.id, AGENT_ID, f"{title}, carefully.")
        SetModuleDataCommand(step.id, STATUS_ID, write_status(status, today=today)).redo(library)
        return step

    sources = [agent_step(title, "in-progress") for title in SOURCES]
    collector = agent_step(COLLECTOR, "pending")
    ids = [source.id for source in sources]
    SetEdgesCommand(collector.id, "requires", ids).redo(library)
    SetModuleDataCommand(collector.id, AUTO_PROGRESS_ID, write_flags(ids)).redo(library)
    services.autosave.flush_now()

    # Another window on this library holds the lock: this one's switch says so.
    set_global(AGENT_ID, AUTO_LAUNCH_KEY, True)
    elsewhere = LaunchLocks(locks).for_library(library_file)
    assert elsewhere.take() == ""
    settings = next(m for m in services.modules if isinstance(m, SettingsModule)).dialog
    settings.show()
    settings.resize(*SETTINGS_SIZE)
    settings.show_section("step_agent_instruction.launch")
    save(settings, out, "settings-another-window", theme, app)
    settings.hide()
    elsewhere.release()

    # That window closed; the sources reach review, and this one launches their collector.
    for source in sources:
        entry = write_status("ready-for-review", today=today)
        SetModuleDataCommand(source.id, STATUS_ID, entry).redo(library)
    services.debounce.flush_all()
    save_top(window, window.notices, out, "notice", theme, app)

    board = services.tabs.open(PROGRESSION_KIND, project.id)
    settle(app)
    services.debounce.flush_all()
    save(board.widget, out, "waits-for-you", theme, app)
    # The switch off again lets the lock go, the way a person's would.
    set_global(AGENT_ID, AUTO_LAUNCH_KEY, False)
    next(m for m in services.modules if m.id == AGENT_ID).settle_launches()
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/f14-auto-launch"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    # Nothing opens: the launch is the real one down to the terminal it would have started.
    launcher.resolve_command = lambda *_args, **_kwargs: ["true"]  # type: ignore[assignment]
    launcher.spawn = lambda *_args, **_kwargs: ""  # type: ignore[assignment]
    with tempfile.TemporaryDirectory(prefix="dplanner-f14-") as tmp:
        # Per-user settings into the throwaway directory, before anything reads them, so the
        # render neither reads nor writes the developer's own.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, f"{tmp}/settings")
        configure_application(app)
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
