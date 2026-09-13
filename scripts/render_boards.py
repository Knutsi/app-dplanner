"""Render the two boards in the dark and the light theme, to PNG.

    uv run python scripts/render_boards.py --out docs/screenshots/s9-boards

Both are real tabs over a synthetic library, because both changes are about what a surface
*stops* saying and no test can see that: the Ready-to-start board is a percent and a bar
with the two count lines gone from under it, and the Order table is the order, the waves
and one volume line where a serial calendar used to run down three columns.
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

from PySide6.QtWidgets import QApplication, QWidget
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.progression.module import PROGRESSION_KIND
from dplanner.modules.step_order.module import ORDER_KIND
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

TAB_SIZE = (1180, 760)
STEPS = 24
# The synthetic plan is a chain, so its frontier is one card wide. These wait on nothing
# and carry an instruction, which is what the Ready lane is for and what the Run Agents
# button counts; two of them unblock the step after, so a card shows its second line, and
# the first is long enough to wrap — which is where the tick's alignment can be read.
READY = (
    "Window chrome: right panel hidden by default, an Index header toolbar, and the "
    "viewport remembered",
    "Specs tab as CRUD: plain-text editors with markdown tools",
    "Design pass: tables and browsers",
)
FOLLOWER = "Dictation in every prose editor, through dictation providers"


def settle(app: QApplication, turns: int = 6) -> None:
    for _ in range(turns):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def add_ready_agents(library: Library, project: Project) -> None:
    ready = []
    for title in READY:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        library.set_text(step.id, "step_agent_instruction", f"{title}, carefully.")
        ready.append(step)
    follower = Step(title=FOLLOWER)
    AddNodeCommand(project.id, follower).redo(library)
    SetEdgesCommand(follower.id, "requires", [ready[0].id, ready[1].id]).redo(library)


def render_boards(app: QApplication, theme: Theme, out: Path, root: Path) -> None:
    session = new_session()
    assert session.open_initial(build_library(root / theme.name, steps=STEPS, projects=1))
    services = session.services
    assert services is not None
    window = session.window
    assert window is not None
    window.resize(*TAB_SIZE)  # The page is a child of the window: sizing it does nothing.
    window.show()
    project = services.document.projects[0]
    add_ready_agents(services.document, project)
    for kind, name in ((PROGRESSION_KIND, "ready-to-start"), (ORDER_KIND, "order")):
        activity = services.tabs.open(kind, project.id)
        settle(app)
        services.debounce.flush_all()
        save(activity.widget, out, name, theme, app)
        if kind == PROGRESSION_KIND:
            # Again with the lane chosen: a click anywhere on a card ticks it, and the face
            # that was greyed while the run was empty says what one press would launch.
            for card in activity.board.ready.cards():
                card.toggle()
            settle(app)
            save(activity.widget, out, f"{name}-ticked", theme, app)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s9-boards"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    configure_application(app)
    with tempfile.TemporaryDirectory(prefix="dplanner-boards-") as tmp:
        for theme in (DARK, LIGHT):
            apply_theme(app, theme)
            render_boards(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
