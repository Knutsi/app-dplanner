"""Render the spec source surfaces in the dark and the light theme, to PNG.

    uv run python scripts/render_spec_sources.py --out docs/screenshots/f5-spec-sources

What F5 added: the Add Spec menu with its four kinds, the Specs tab showing a folder
source's nested documents with the strip above them, the Add Git Repository dialog with
the remote's folders listed, and the Confluence Connect dialog brought onto
``DialogFrame``. A whole application is built over a throwaway library so nothing here
hand-wires a surface the window would build differently; the git dialog's probe is a
plain function, because a render script reaches no network.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QBuffer, QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QFileDialog, QSplitter, QWidget

from dplanner.app import new_session
from dplanner.core.storage.locations import init_repo
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.action_menu import build_menu
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.modules.spec_confluence.connect import ConnectDialog
from dplanner.modules.spec_git.connect import GitSourceDialog
from dplanner.modules.spec_git.source import Folder, Probe
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

TAB_SIZE = (1000, 640)
DIALOG_SIZE = (620, 640)
CONNECT_SIZE = (560, 520)

FOUND = Probe(
    ref="main",
    folders=(
        Folder(path="", files=4182, documents=918),
        Folder(path="docs", files=64, documents=41),
        Folder(path="docs/spec", files=22, documents=19),
        Folder(path="docs/adr", files=18, documents=18),
        Folder(path="src", files=4042, documents=842),
    ),
)


def diagram() -> bytes:
    """A picture for the spec to link, drawn rather than pasted in as a literal."""
    image = QImage(240, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("#4c6ef5"))
    painter = QPainter(image)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, "the flow")
    painter.end()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


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


def specs_folder(root: Path) -> Path:
    """A small documentation tree: an index at the top, a subdirectory with its own."""
    folder = root / "product specs"
    (folder / "design" / "images").mkdir(parents=True)
    (folder / "README.md").write_text(
        "# Quick registration\n\nWhat the product is, and who it is for.\n"
    )
    (folder / "glossary.md").write_text("# Glossary\n\nThe words this spec uses.\n")
    (folder / "design" / "README.md").write_text("# Design\n\nHow the screens fit together.\n")
    (folder / "design" / "auth.md").write_text(
        "# Authentication\n\nThe modal, and what it asks for.\n\n![the flow](images/flow.png)\n"
    )
    (folder / "design" / "images" / "flow.png").write_bytes(diagram())
    (folder / "design" / "tokens.md").write_text("# Tokens\n\nHow long a session lasts.\n")
    return folder


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

    directory = seed_project(workspace / f"discovery-{theme.name}", "Quick registration")
    project = services.repo.attach(directory)
    services.document.add_child(services.document.id, project)
    services.context.set_scope(
        SCOPE_SELECTION, (ContextNode(selection_uri("project", project.id)),)
    )
    settle(app)

    # The + button's arrow drops the Project ▸ Add Spec child menu: four kinds after the
    # two built-ins, each with the glyph its rows wear.
    menu = build_menu(
        services.actions, services.context, "Project", services.window, submenu="Add Spec"
    )
    menu.popup(services.window.mapToGlobal(services.window.rect().topLeft()))
    settle(app)
    save(menu, out, "add-spec-menu", theme, app)
    menu.hide()
    discard(menu)

    # A folder source, added through the kind's own verb: the dialog is the only thing
    # standing in, because a render script has nobody to pick a folder.
    folder = specs_folder(workspace / f"source-{theme.name}")
    real = QFileDialog.getExistingDirectory
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(folder))  # type: ignore[assignment]
    try:
        services.actions.run("spec.add_source.folder", services.context.current())
    finally:
        QFileDialog.getExistingDirectory = real  # type: ignore[assignment]
    settle(app)
    activity = services.tabs.activities()[0]
    activity.select_document("authentication")
    settle(app)
    # Off the tab host, so the render is the surface's own size and not the window's.
    widget = activity.widget
    host = widget.parentWidget()
    widget.setParent(None)
    widget.resize(*TAB_SIZE)
    widget.show()
    settle(app)
    # The splitter starts at its stretch factors over the tab's width; give the list the
    # room a person would drag it to, so the titles read.
    splitter = widget.findChild(QSplitter)
    if splitter is not None:
        splitter.setSizes([340, TAB_SIZE[0] - 340])
    save(widget, out, "specs-tab-folder-source", theme, app)
    widget.setParent(host)

    # The git dialog, over a listing a real probe would have brought back.
    git = GitSourceDialog(None, tasks=services.tasks, probe=lambda _u, _r: FOUND)
    git.url.setText("https://github.com/acme/handbook.git")
    git.ref.setText("main")
    git._on_probed(FOUND, "")
    git.table.selectRow(2)
    git.resize(*DIALOG_SIZE)
    git.show()
    save(git, out, "git-source-dialog", theme, app)
    discard(git)

    # The same dialog meeting the size guard: a monorepo's root is too much to take in,
    # and the refusal names the folder and says what to do, in the footer's status slot.
    git = GitSourceDialog(None, tasks=services.tasks, probe=lambda _u, _r: FOUND)
    git.url.setText("https://github.com/acme/handbook.git")
    git._on_probed(FOUND, "")
    git.table.selectRow(0)
    git.resize(*DIALOG_SIZE)
    git.show()
    save(git, out, "git-source-refused", theme, app)
    discard(git)

    # Confluence's Connect dialog, now on the frame.
    connect = ConnectDialog(
        None,
        "https://acme.atlassian.net",
        tasks=services.tasks,
        probe=lambda _c: "Auth Overview",
        open_url=lambda _u: None,
        backend_problem=None,
        email="me@acme.example",
    )
    connect.token.setText("a-token")
    connect._on_probed("Auth Overview", "")
    connect.resize(*CONNECT_SIZE)
    connect.show()
    save(connect, out, "confluence-connect", theme, app)
    discard(connect)

    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the PNGs")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    with TemporaryDirectory(prefix="dplanner-render-") as tmp:
        for theme in (DARK, LIGHT):
            render(app, theme, args.out, Path(tmp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
