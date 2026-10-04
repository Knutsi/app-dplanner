"""Render the step detail dialog in the dark and the light theme, to PNG.

    uv run python scripts/render_step_details.py --out docs/screenshots/s6-step-details
    uv run python scripts/render_step_details.py --start --out docs/screenshots/f2-start-marker
    uv run python scripts/render_step_details.py --review \
        --out docs/screenshots/f12-automatic-review
    uv run python scripts/render_step_details.py --conversation \
        --out docs/screenshots/s35-review-conversation

The surfaces S6 reworked: the aspect bar's toggles on the left and the template it amounts
to on the right, the Details tab stacking from the top whatever is turned off, and the
dialog on ``DialogFrame`` with one Close in its footer. The panel has one host — the dialog
``steps.details`` opens — so every image here is of that, reached through the verb rather
than hand-wired, over a whole application built on a throwaway library and torn down per
theme. ``--start`` renders F2's instead: the same dialog on a plan's start, and the
Step ▸ Type menu that marks it. ``--review`` renders F12's: the Review tab of a review two
rounds into its conversation, and the templates with Review ticked. ``--conversation``
renders S35's: that same conversation read in full, in the dialog *Review Conversation…*
opens.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.app import new_session
from dplanner.core.storage.locations import init_repo
from dplanner.domain.commands import AddNodeCommand, SetEdgesCommand, SetModuleDataCommand
from dplanner.domain.model import Library, Step
from dplanner.domain.seed import create_library, seed_project
from dplanner.framework.action_menu import build_menu
from dplanner.framework.context import (
    SCOPE_SELECTION,
    ContextNode,
    selection_uri,
)
from dplanner.framework.services import AppServices
from dplanner.modules.step_properties.dialog import StepDetailsDialog
from dplanner.modules.step_review.aspect import MODULE_ID as ROUNDS_ID
from dplanner.modules.step_review.aspect import opened, said
from dplanner.modules.step_review.conversation_dialog import DIALOG_SIZE as CONVERSATION_SIZE
from dplanner.modules.step_review.conversation_dialog import ConversationDialog
from dplanner.planning.agent import MODULE_ID as AGENT_ID
from dplanner.planning.agent import write_state as agent_write
from dplanner.planning.review import MODULE_ID as REVIEW_ID
from dplanner.planning.review import ReviewSettings
from dplanner.planning.review import write as review_write
from dplanner.planning.start import MODULE_ID as START_ID
from dplanner.planning.start import write as start_write
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme

DIALOG_SIZE = (900, 760)

# F12: what a reviewer and the reviewed agent said, two rounds in — the second still open
# with the reviewed step, so the tab says whose turn it is.
CONVERSATION = (
    (
        "2026-09-27T09:12:00+00:00",
        "The parser drops trailing whitespace inside quoted fields.\nNo test covers empty input.",
        "2026-09-27T10:40:00+00:00",
        "Whitespace is kept inside quotes now, and empty input has a test of its own.",
    ),
    (
        "2026-09-27T11:05:00+00:00",
        "The error for an unclosed quote names no line number.\n\n"
        "Somebody importing a four-thousand-line file cannot find the quote it means. "
        "Two changes would fix it:\n\n"
        "- say the line and the column where the quote opened;\n"
        "- keep the message to one line, so a terminal does not wrap it.\n\n"
        "`test_errors.py` checks only that an error is raised, not what it says.",
        "",
        "",
    ),
)


def converse(library: Library, review: Step, subject: Step) -> None:
    """Write the conversation the way the verbs would, round by round."""
    for posted, findings, replied, reply in CONVERSATION:
        entry = opened(review, subject.id, posted)
        SetModuleDataCommand(review.id, ROUNDS_ID, entry).redo(library)
        entry = said(review, subject.id, findings=findings, posted=posted)
        SetModuleDataCommand(review.id, ROUNDS_ID, entry).redo(library)
        if replied:
            entry = said(review, subject.id, reply=reply, replied=replied)
            SetModuleDataCommand(review.id, ROUNDS_ID, entry).redo(library)


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


def render_conversation(services: AppServices, out: Path, theme: Theme, app: QApplication) -> None:
    """The dialog *Review Conversation…* opens, through the verb — rendered where it would
    block, and disposed by the verb on its way out as it always is."""

    def shown(dialog: ConversationDialog) -> int:
        dialog.show()
        dialog.resize(*CONVERSATION_SIZE)  # After show: the offscreen screen clamps a framed size.
        save(dialog, out, "conversation", theme, app)
        dialog.hide()
        return 0

    real_exec = ConversationDialog.exec
    ConversationDialog.exec = shown  # type: ignore[method-assign, assignment]
    try:
        services.actions.run("review.conversation", services.context.current())
    finally:
        ConversationDialog.exec = real_exec  # type: ignore[method-assign]
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def render(
    app: QApplication,
    theme: Theme,
    out: Path,
    workspace: Path,
    *,
    start: bool,
    review: bool,
    conversation: bool,
) -> None:
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
    step = Step(title="Project start" if start else "Build the quick-reg modal")
    if start:
        step.module_data[START_ID] = start_write(True)
    AddNodeCommand(project.id, step).redo(services.document)
    if review or conversation:
        # The step above is the subject; the dialog opens on its review.
        subject, step = step, Step(title="Review the quick-reg modal")
        AddNodeCommand(project.id, step).redo(services.document)
        for each in (subject, step):
            SetModuleDataCommand(each.id, AGENT_ID, agent_write(True)).redo(services.document)
        SetModuleDataCommand(step.id, REVIEW_ID, review_write(ReviewSettings())).redo(
            services.document
        )
        SetEdgesCommand(step.id, "requires", [subject.id]).redo(services.document)
        converse(services.document, step, subject)
    services.context.set_scope(SCOPE_SELECTION, (ContextNode(selection_uri("step", step.id)),))
    settle(app)
    if conversation:
        render_conversation(services, out, theme, app)
        session.close()
        return

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
    if review:
        panel = dialog.panel
        labels = [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]
        panel.tab_bar.setCurrentIndex(labels.index("Review"))
        save(dialog, out, "review-tab", theme, app)
        bar = panel.bar
        bar.face.menu().popup(dialog.mapToGlobal(bar.face.pos()))
        settle(app)
        save(bar.face.menu(), out, "review-templates", theme, app)
        bar.face.menu().hide()
        real_dispose(dialog)
        discard(dialog)
        session.close()
        return
    if start:
        save(dialog, out, "start-dialog", theme, app)
        # The Type submenu the bar renders: Start ticked among the kinds, after Wait.
        menu = build_menu(services.actions, services.context, "Step", dialog, submenu="Type")
        menu.popup(dialog.mapToGlobal(dialog.rect().topLeft()))
        save(menu, out, "start-type", theme, app)
        menu.hide()
        discard(menu)
        real_dispose(dialog)
        discard(dialog)
        session.close()
        return
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
    parser.add_argument(
        "--start", action="store_true", help="render a plan's start step instead (F2)"
    )
    parser.add_argument(
        "--review", action="store_true", help="render a review step's Review tab instead (F12)"
    )
    parser.add_argument(
        "--conversation",
        action="store_true",
        help="render a review's conversation dialog instead (S35)",
    )
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    # The throwaway library lives outside the output directory: what lands there is images.
    with TemporaryDirectory(prefix="dplanner-render-") as tmp:
        # The per-user settings go to the same throwaway place: a render reads none of this
        # machine's (the Review tab names the default launch profile) and writes none.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tmp)
        for theme in (DARK, LIGHT):
            render(
                app,
                theme,
                args.out,
                Path(tmp),
                start=args.start,
                review=args.review,
                conversation=args.conversation,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
