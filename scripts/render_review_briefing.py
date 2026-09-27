"""Render what S13 made visible, in the dark and the light theme, to PNG.

    uv run python scripts/render_review_briefing.py --out docs/screenshots/s13-review-briefing

One surface, one step: the Agent tab on a **review**. Its *Fresh git worktree* box stands
unticked and greyed — a review reads the work it reviews where that work is, so no run of
it gets a worktree whatever the aspect says — and its Prompt pane is the briefing that run
is launched with: the preflight telling it to leave the checkout as it found it, *Work you
review*, and the generated instructions.
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

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget
from scripts.synthetic_library import build_library

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.domain.commands import SetEdgesCommand
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.github.aspect import MODULE_ID as GITHUB_ID
from dplanner.modules.github.aspect import GithubRefs
from dplanner.modules.github.aspect import write as github_write
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state
from dplanner.modules.step_review.aspect import MODULE_ID as REVIEW_ID
from dplanner.modules.step_review.aspect import ReviewSettings
from dplanner.modules.step_review.aspect import write as review_write
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

STEPS = 8
PANEL_SIZE = (560, 1000)  # The step panel's width, tall enough to reach the instructions.


def settle(app: QApplication, turns: int = 4) -> None:
    for _ in range(turns):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def render(app: QApplication, theme: Theme, out: Path, root: Path) -> None:
    session = new_session()
    assert session.open_initial(build_library(root / theme.name, steps=STEPS, projects=1))
    services = session.services
    assert services is not None
    window = session.window
    assert window is not None
    window.show()
    library = services.document
    project = library.projects[0]
    # Two plain steps, so the review's key reads R rather than a coarser kind's letter.
    kinds = ("step_check", "step_milestone", "feature", "step_wait")
    plain = [step for step in project.steps if not any(k in step.module_data for k in kinds)]
    subject, review = plain[-2], plain[-1]
    library.set_module_data(
        subject.id, GITHUB_ID, github_write(GithubRefs(branch="agent/s7-parser", pr_number=42))
    )
    SetEdgesCommand(review.id, "requires", [subject.id]).redo(library)
    library.set_module_data(review.id, AGENT_ID, write_state(True))
    library.set_module_data(
        review.id, REVIEW_ID, review_write(ReviewSettings(lenses=("architecture", "perf")))
    )
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", review.id)),))
    settle(app)

    spec = next(
        s for s in services.inspector_sections.sections() if s.id == "step_agent_instruction.tab"
    )
    section = spec.factory()
    section.widget.resize(*PANEL_SIZE)
    section.show_target(review.id)
    section.widget.show()
    save(section.widget, out, "agent-tab-review", theme, app)
    section.dispose()
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s13-review-briefing"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    with tempfile.TemporaryDirectory(prefix="dplanner-review-briefing-") as tmp:
        # A throwaway settings directory before anything reads one, as the suite's conftest
        # does: the developer's own profiles must neither appear nor be written to.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        app = QApplication.instance() or QApplication(sys.argv[:1])
        assert isinstance(app, QApplication)
        for theme in (DARK, LIGHT):
            QSettings.setPath(
                QSettings.Format.IniFormat,
                QSettings.Scope.UserScope,
                str(Path(tmp) / f"settings-{theme.name}"),
            )
            configure_application(app)
            apply_theme(app, theme)
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
