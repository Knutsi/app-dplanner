"""Render what this pass made visible, in the dark and the light theme, to PNG.

    uv run python scripts/render_briefing_size.py --out docs/screenshots/s2-briefing-size

Three surfaces. The Agent tab's **Prompt** pane, whose legend now ends with what the briefing
comes to — the question somebody reading those colours is already asking. Its **Notes** pane,
over a project with more decisions than an index carries, so the capped group and the line
naming what it left out are both in the picture. And the **Agents browser**, where a run says
what it was handed: the live one from its own record, before any token can be read back, and
the ended one beside what it spent.
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
from dplanner.domain.commands import SetModuleDataCommand
from dplanner.domain.model import Library, Project
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.notes.log import MODULE_ID as NOTES_ID
from dplanner.modules.notes.log import Note, write_log
from dplanner.modules.step_agent_instruction.aspect import MODULE_ID as AGENT_ID
from dplanner.modules.step_agent_instruction.aspect import write_state
from dplanner.modules.step_agent_run.aspect import MODULE_ID as RUNS_ID
from dplanner.modules.step_agent_run.usage import Usage, record, row_for
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

STEPS = 24
PANEL_SIZE = (560, 720)  # The step panel at a width the right dock actually gets.
# Taller for the Notes pane alone: the line saying what the index left out is the point
# of that picture, and at the panel's own height it falls below the fold.
NOTES_HEIGHT = 1080
BROWSER_SIZE = (720, 400)
# Enough decisions that the group is capped and has to say so, plus a few of each other
# label so the index reads as an index rather than one list.
DECISIONS = 28
BRIEFED = 17_841  # The median briefing on the 74-step plan this pass was measured against.


def settle(app: QApplication, turns: int = 4) -> None:
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


def write_notes(library: Library, project: Project) -> None:
    """A log whose decisions outrun the index's ceiling, every note on the first step so all
    of them reach the one being briefed."""
    made_on = project.steps[0].id
    notes = [
        Note(
            f"N{n}",
            "decision",
            TITLES[n % len(TITLES)],
            "Why it went that way, and what it cost.",
            f"2026-09-{1 + n % 12:02d}",
            made_on,
        )
        for n in range(1, DECISIONS + 1)
    ]
    notes += [
        Note(
            "N101",
            "handoff",
            "The importer is stubbed past the second page",
            made="2026-09-11",
            step=made_on,
        ),
        Note(
            "N102",
            "spec-change",
            "The spec's retry budget was three, not one",
            made="2026-09-11",
            step=made_on,
        ),
        Note(
            "N103",
            "later",
            "Fifteen modules still spell the gap by hand",
            made="2026-09-12",
            step=made_on,
        ),
    ]
    SetModuleDataCommand(project.id, NOTES_ID, write_log(notes)).redo(library)


TITLES = (
    "The accent primary is one type-prefixed rule, last in theme.qss",
    "Table row height is derived from the font; tokens are the paddings",
    "A refused primary is disabled and keeps its name",
    "No header sorting on tables",
    "colors.toml maps by its anchors; the ramps are derived",
    "A strip of verbs is a Toolbar, folding into a … menu",
    "The milestone colour map stays the project's",
)


def run_dir(root: Path, name: str) -> Path:
    made = root / "runs" / name
    made.mkdir(parents=True, exist_ok=True)
    return made


def agent_section(services, step_id: str):
    spec = next(
        s for s in services.inspector_sections.sections() if s.id == "step_agent_instruction.tab"
    )
    section = spec.factory()
    section.widget.resize(*PANEL_SIZE)
    section.show_target(step_id)
    return section


def render(app: QApplication, theme: Theme, out: Path, root: Path) -> None:
    session = new_session()
    assert session.open_initial(build_library(root / theme.name, steps=STEPS, projects=1))
    services = session.services
    assert services is not None
    window = session.window
    assert window is not None
    window.show()
    project = services.document.projects[0]
    step = project.steps[-1]
    write_notes(services.document, project)
    services.document.set_module_data(step.id, AGENT_ID, write_state(True))
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))
    settle(app)

    section = agent_section(services, step.id)
    section.widget.show()
    save(section.widget, out, "agent-prompt", theme, app)
    # Components, with the Notes part open: the index, capped, saying what it left out.
    section.tab_bar.setCurrentIndex(1)
    section.inherited_part.set_expanded(True)
    section.widget.resize(PANEL_SIZE[0], NOTES_HEIGHT)
    save(section.widget, out, "agent-notes", theme, app)
    section.dispose()

    # One run still going and one over, which is the pair the row exists to tell apart: the
    # live one says its size off its own record, before any token can be read back.
    runs = next(m for m in services.modules if m.id == RUNS_ID)
    # A directory each: a run's identity *is* its run directory, so two runs sharing one
    # would be one row.
    live_dir = run_dir(root / theme.name, "live")
    done_dir = run_dir(root / theme.name, "done")
    runs.track(step.id, str(live_dir / "shell"), str(live_dir / "exit"), "claude", "s1", BRIEFED)
    # This process's own pid: `settle` asks whether the shell is alive, and ours is.
    (live_dir / "shell").write_text(f"pid={os.getpid()}\n")
    other = project.steps[-2]
    runs.track(other.id, str(done_dir / "shell"), str(done_dir / "exit"), "claude", "s2", 12_402)
    (done_dir / "exit").write_text("0\n")
    record(services.document, other.id, row_for("claude", "s2", Usage(120_400, 8_310), "", 12_402))
    runs.check()
    runs._open_browser()
    browser = runs._browser
    browser.resize(*BROWSER_SIZE)
    save(browser, out, "agents-browser", theme, app)
    discard(browser)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s2-briefing-size"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    with tempfile.TemporaryDirectory(prefix="dplanner-briefing-size-") as tmp:
        # A throwaway settings directory before anything reads one, exactly as the suite's
        # conftest does: the Agents browser renders the *runs*, which are a per-user fact —
        # the developer's own must neither appear in the picture nor be written to by it.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        app = QApplication.instance() or QApplication(sys.argv[:1])
        assert isinstance(app, QApplication)
        for theme in (DARK, LIGHT):
            # Per theme, so the first pass's runs are not still in the second's browser.
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
