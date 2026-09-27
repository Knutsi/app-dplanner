"""Render the Step statuses tab and the Order table in the dark and the light theme, to PNG.

    uv run python scripts/render_boards.py --out docs/screenshots/f6-step-statuses

Both are real tabs over a synthetic library. Step statuses is rendered three ways: every
group, then with the reviews ticked — the strip's verbs lit for what the ticks can take —
and filtered to one group, where the heading stands down because the filter says it.
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

from PySide6.QtWidgets import QApplication, QWidget
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Project, Step
from dplanner.modules.progression.module import PROGRESSION_KIND
from dplanner.modules.step_order.module import ORDER_KIND
from dplanner.modules.step_status.aspect import MODULE_ID as STATUS_ID
from dplanner.modules.step_status.aspect import write as write_status
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

TAB_SIZE = (1180, 760)
STEPS = 24
# The synthetic plan is a chain, so its frontier is one step wide. These wait on nothing
# and carry an instruction: two came back from their agents, one is accepted and waits on
# its merge, and two are ready to start: rows in every group a person acts on.
REVIEWED = (
    "Window chrome: right panel hidden by default, an Index header toolbar, and the "
    "viewport remembered",
    "Specs tab as CRUD: plain-text editors with markdown tools",
)
MERGING = ("Design pass: tables and browsers",)
READY = ("Dictation in every prose editor", "Card icons: sparkle for agent work")
FOLLOWER = "Auto-progress links: parallel work handed to a collector"


def settle(app: QApplication, turns: int = 6) -> None:
    for _ in range(turns):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def add_ready_agents(library: Library, project: Project) -> None:
    made = []
    for title, word in (
        *((title, "ready-for-review") for title in REVIEWED),
        *((title, "ready-to-merge") for title in MERGING),
        *((title, "") for title in READY),
    ):
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        library.set_text(step.id, "step_agent_instruction", f"{title}, carefully.")
        if word:
            entry = write_status(word, today=date.today())
            SetModuleDataCommand(step.id, STATUS_ID, entry).redo(library)
        made.append(step)
    follower = Step(title=FOLLOWER)
    AddNodeCommand(project.id, follower).redo(library)
    SetEdgesCommand(follower.id, "requires", [made[0].id, made[2].id]).redo(library)


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
    for kind, name in ((PROGRESSION_KIND, "step-statuses"), (ORDER_KIND, "order")):
        activity = services.tabs.open(kind, project.id)
        settle(app)
        services.debounce.flush_all()
        save(activity.widget, out, name, theme, app)
        if kind == PROGRESSION_KIND:
            # The reviews ticked: the strip lights what the ticks can take.
            table = activity.table
            for row in range(table.rowCount()):
                if table.item(row, 1) is not None and table.item(row, 1).text() in REVIEWED:
                    table.toggle_row(row)
            settle(app)
            services.debounce.flush_all()
            save(activity.widget, out, f"{name}-ticked", theme, app)
            activity.set_filter("review")
            settle(app)
            save(activity.widget, out, f"{name}-review", theme, app)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/f6-step-statuses"))
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
