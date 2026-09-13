"""Render the Specs tab's surfaces in the dark and the light theme, to PNG.

    uv run python scripts/render_specs_tab.py --out docs/screenshots/s12-specs-tab

What S12 changed: the editor is the prose stack's — plain text under a markdown strip,
with the figures it links to in a gallery beneath it — the tab's two strips are `Toolbar`s
of glyphs over a `StatusLine`, a source with updates says so over the whole tree and marks
the tab's own title, and Rename is a `LinePrompt`. A whole application is built over a
throwaway library, so nothing here hand-wires a surface the window would build differently.
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
from dplanner.domain.document_source import Freshness
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.context import SCOPE_SELECTION, ContextNode, selection_uri
from dplanner.framework.dialog import LinePrompt
from dplanner.framework.text_dialog import ExpandedTextDialog
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

TAB_SIZE = (1100, 680)
LIST_WIDTH = 320
PROMPT_SIZE = (460, 220)
EXPANDED_SIZE = (900, 600)

SPEC = """# Authentication

Operators sign in with an e-mail address and a one-time code. The code is good
for ten minutes and may be asked for again once.

## What the modal asks for

- the e-mail address, which is also the account key
- the code, six digits, pasted or typed
- *Remember this computer*, which is off by default

The flow, end to end:

![the flow](assets/flow.png)

| Step | Who | What happens |
| --- | --- | --- |
| 1 | operator | asks for a code |
| 2 | service | sends one, and waits |

Use `POST /sessions` to start one. See [the token rules](tokens.md) for how long
a session lasts.
"""


def diagram() -> bytes:
    """A picture for the spec to link, drawn rather than pasted in as a literal."""
    image = QImage(320, 140, QImage.Format.Format_RGB32)
    image.fill(QColor("#4c6ef5"))
    painter = QPainter(image)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, "the sign-in flow")
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
    """A small documentation tree, so the tab shows a source's pages beside its own."""
    folder = root / "product specs"
    folder.mkdir(parents=True)
    (folder / "README.md").write_text("# Quick registration\n\nWhat the product is.\n")
    (folder / "glossary.md").write_text("# Glossary\n\nThe words this spec uses.\n")
    (folder / "rollout.md").write_text("# Rollout\n\nWho gets it when.\n")
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

    # The project's own document, written through the verbs a person has: created, then
    # typed into, then given a picture the way a paste gives one.
    from dataclasses import replace as _replace

    from dplanner.domain.commands import SetModuleDataCommand
    from dplanner.modules.spec.aspect import MODULE_ID
    from dplanner.modules.spec.documents import (
        attach_asset,
        import_document,
        read_index,
        write_index,
    )

    area = services.repo.files(project.id, MODULE_ID)
    body = SPEC.replace("assets/flow.png", attach_asset(area, diagram(), "flow.png"))
    index = read_index(services.document.project(project.id))
    documents, _document, _outcome = import_document(
        area, index.documents, "authentication", body.encode(), "authentication.md", "2026-09-13"
    )
    SetModuleDataCommand(
        project.id, MODULE_ID, write_index(_replace(index, documents=documents))
    ).redo(services.document)

    # A folder source beside it, so the tree shows both halves and the strip has a source.
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
    splitter = widget.findChild(QSplitter)
    if splitter is not None:
        splitter.setSizes([LIST_WIDTH, TAB_SIZE[0] - LIST_WIDTH])
    settle(app)
    save(widget, out, "specs-tab-editor", theme, app)

    # The same tab with a source that has updates: the line over the tree counts them, the
    # strip says what this one found, and the tab's own title wears the mark.
    refresher = activity._refresher
    assert refresher is not None
    refresher._freshness[(project.id, "src1")] = Freshness(changed=("glossary.md",), added=("a",))
    activity.select_source("src1")
    activity._refresh_source_strip()
    settle(app)
    save(widget, out, "specs-tab-source-updates", theme, app)
    widget.setParent(host)

    # Rename, on the one-line prompt, refusing a name another document already answers to.
    prompt = LinePrompt(
        "Rename Spec Document",
        "Name — what every command addresses it by",
        "Rename",
        None,
        text="glossary",
        validate=lambda _typed: "a spec document named 'glossary' already exists",
    )
    prompt.resize(*PROMPT_SIZE)
    prompt.show()
    settle(app)
    save(prompt, out, "specs-rename-prompt", theme, app)
    discard(prompt)

    # The editor in a window of its own — the same document, the same strip.
    expanded = ExpandedTextDialog.over_document(
        activity._editor.document(), services.undo, title="authentication"
    )
    expanded.resize(*EXPANDED_SIZE)
    expanded.show()
    settle(app)
    save(expanded, out, "specs-expanded-editor", theme, app)
    expanded.dispose()
    discard(expanded)

    session.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/s12-specs-tab"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    for theme in (DARK, LIGHT):
        with TemporaryDirectory() as temporary:
            render(app, theme, args.out, Path(temporary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
