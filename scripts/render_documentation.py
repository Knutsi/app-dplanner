"""Render the Documentation tab in the dark and the light theme, to PNG.

    uv run python scripts/render_documentation.py --out docs/screenshots/s11-documentation

A real session over a library the script builds itself, because the three states worth seeing
are rarely all true at once and ``scripts/synthetic_library.py`` writes no fragments: one
collector's documentation current, one out of date, one never compiled, and an agent at work
on a fourth. Three images per theme — the list with its rows, the strip's profile dropdown,
and the compilation instructions the briefings open with.
"""

import argparse
import io
import os
import sys
import tempfile
import time
from pathlib import Path

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QWidget

from dplanner.app import configure_application, new_session, set_early_attributes
from dplanner.cli.discovery import open_library
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import (
    AddNodeCommand,
    SetEdgesCommand,
    SetModuleDataCommand,
)
from dplanner.domain.model import Library, Project, Step
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.user_config import set_global
from dplanner.modules import default_module_formats
from dplanner.modules.docs.activity import DOCS_KIND
from dplanner.modules.docs.aspect import COMPILED_ID, MODULE_ID, write_stamp, write_state
from dplanner.modules.docs.collect import digest, sources_for
from dplanner.modules.docs.module import COMPILE_ACTION, LAUNCHES_KEY
from dplanner.modules.feature.aspect import write as feature_write
from dplanner.modules.step_agent_run.aspect import record_launch
from dplanner.modules.step_milestone.aspect import write as milestone_write
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

TAB_SIZE = (1180, 760)
COMPILED_BY = "Claude Code · session 3f2a1c74"

# One project's worth of work: three features under a milestone, each a different state.
FRAGMENTS = {
    "Parse the query string": "Search accepts `field:value` pairs and bare words. Quote a"
    " phrase to keep it together, and put a minus in front of a term to exclude it.",
    "Rank the results": "Results come back most-relevant first. A match in a title outranks"
    " one in the body, and a recent document outranks an old one at the same score.",
    "Save a search": "Give a search a name and it appears in the sidebar. A saved search is"
    " re-run every time you open it, so it stays current as work lands.",
    "Export to CSV": "Any result list exports as CSV: one row per result, the columns you"
    " have on screen, in the order you put them.",
}
FEATURES = {
    "Search": ["Parse the query string", "Rank the results"],
    "Saved searches": ["Save a search"],
    "Export": ["Export to CSV"],
}
DOCUMENTS = {
    "Search": "# Searching\n\nType `field:value` pairs or bare words into the search box.",
    "Saved searches": "# Saved searches\n\nName a search and it appears in your sidebar.",
}


def settle(app: QApplication, turns: int = 6) -> None:
    for _ in range(turns):
        app.processEvents()


def save(widget: QWidget, out: Path, name: str, theme: Theme, app: QApplication) -> None:
    settle(app)
    path = out / f"{name}-{theme.name}.png"
    widget.grab().save(str(path), "PNG")
    print(path)


def build(root: Path) -> Path:
    """A library whose one project has all three states on screen at once.

    Written through the CLI's ``open_library``, as ``scripts/synthetic_library.py`` is, so the
    plan lands on disk in the real format and the window opens it as it would any other.
    """
    root.mkdir(parents=True, exist_ok=True)
    library_file = root / "library.json"
    create_library(library_file)
    repo = init_repo(root / "plans")
    with open_library(library_file, default_module_formats(), io.StringIO()) as context:
        project = context.store.attach(seed_project(repo / "search-rewrite", "Search Rewrite"))
        context.library.add_child(context.library.id, project)
        _fill(context.library, project)
    return library_file


def _fill(library: Library, project: Project) -> None:
    steps: dict[str, Step] = {}
    for title in FRAGMENTS:
        step = Step(title=title)
        AddNodeCommand(project.id, step).redo(library)
        steps[title] = step
        library.set_text(step.id, MODULE_ID, FRAGMENTS[title])
        SetModuleDataCommand(step.id, MODULE_ID, write_state(True)).redo(library)
    for name, held in FEATURES.items():
        feature = Step(title=name)
        AddNodeCommand(project.id, feature).redo(library)
        steps[name] = feature
        SetModuleDataCommand(feature.id, "feature", feature_write(name.lower())).redo(library)
        SetEdgesCommand(feature.id, "requires", [steps[t].id for t in held]).redo(library)
    release = Step(title="Ship the rewrite")
    AddNodeCommand(project.id, release).redo(library)
    SetModuleDataCommand(release.id, "step_milestone", milestone_write("v2")).redo(library)
    SetEdgesCommand(release.id, "requires", [steps[n].id for n in FEATURES]).redo(library)

    library.set_text(project.id, MODULE_ID, COMPILATION_INSTRUCTIONS)
    # Two documents compiled. Search's is current; Saved searches' went out of date when the
    # fragment behind it was edited after the compile, which is the digest doing its work.
    for name, body in DOCUMENTS.items():
        step = steps[name]
        library.set_text(step.id, COMPILED_ID, body)
        found = sources_for((), library, project, step.id)
        stamp = write_stamp(digest(found), time.time() - 2 * 24 * 3600, len(found))
        SetModuleDataCommand(step.id, COMPILED_ID, stamp).redo(library)
    library.set_text(steps["Save a search"].id, MODULE_ID, FRAGMENTS["Save a search"] + " Rename")
    # An agent at work on the one nobody has compiled yet, and a launch this desk remembers.
    record_launch(library, steps["Export"].id)
    set_global(MODULE_ID, LAUNCHES_KEY, {steps[name].id: COMPILED_BY for name in DOCUMENTS})


COMPILATION_INSTRUCTIONS = (
    "Second person, present tense. Describe what somebody can do, never what the team built."
    " One heading per thing a reader would look up, and no release notes: the milestone's"
    " document is where a change is announced."
)


def render(app: QApplication, theme: Theme, out: Path, root: Path) -> None:
    apply_theme(app, theme)
    session = new_session()
    assert session.open_initial(build(root / theme.name))
    services = session.services
    assert services is not None
    window = session.window
    assert window is not None
    window.resize(*TAB_SIZE)  # The page is a child of the window: sizing it does nothing.
    window.show()
    project = services.document.projects[0]
    activity = services.tabs.open(DOCS_KIND, project.id)
    page = activity.widget
    settle(app)
    services.debounce.flush_all()
    settle(app)

    save(page, out, "documentation", theme, app)

    # The strip's arrow: the launch profiles, which is the Step menu's own child menu.
    menu = page.controls.menu_for(page.verbs[COMPILE_ACTION])
    if menu is not None:
        button = page.controls.childAt(page.verbs[COMPILE_ACTION].associatedObjects()[0].pos())
        del button  # The popup is what is photographed; its placement is Qt's.
        menu.popup(page.mapToGlobal(page.rect().topLeft()))
        save(menu, out, "documentation-profiles", theme, app)
        menu.hide()

    page.tabs.setCurrentIndex(page.tabs.count() - 1)
    save(page, out, "documentation-instructions", theme, app)
    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s11-documentation"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    set_early_attributes()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    configure_application(app)
    with tempfile.TemporaryDirectory(prefix="dplanner-documentation-") as tmp:
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
