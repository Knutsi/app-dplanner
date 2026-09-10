"""Ctrl+Z reaches the application's stack from a window of its own.

The menu bar's Undo is a *window* shortcut of the main window, so a dialog is a window in
which nobody answers the key: :class:`TextBinding` has given it up (its own history is off)
and the menu bar is out of context. These tests deliver a real key through the platform, so
they exercise the whole path — shortcut override, shortcut map, action — rather than calling
a slot.
"""

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from dplanner.domain.commands import AddNodeCommand
from dplanner.domain.fields import ModuleTextField
from dplanner.domain.model import Step
from dplanner.framework.text_dialog import ExpandedTextDialog

MODULE_ID = "step_description"
SRC = Path(__file__).parent.parent.parent / "src" / "dplanner"


@pytest.fixture(autouse=True)
def _no_launch_notice(monkeypatch):
    """A window-modal box over the window swallows every key event bound for it, and the
    missing-gh warning opens one on the first turn of the event loop after a build."""
    from dplanner.modules.github import notice

    monkeypatch.setattr(notice, "_warned_this_process", True)


@pytest.fixture
def step(services, make_project):
    project = make_project("Discovery")
    step = Step(title="Deploy")
    AddNodeCommand(project.id, step).redo(services.document)
    return step


def press(dialog, key, modifiers=Qt.KeyboardModifier.ControlModifier):
    QTest.keyClick(dialog.windowHandle(), key, modifiers)
    QTest.qWait(1)


def test_ctrl_z_in_an_expanded_editor_undoes_the_typing(services, step, qtbot):
    dialog = ExpandedTextDialog(
        ModuleTextField(services.document, step.id, MODULE_ID),
        services.undo,
        title="Description",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.activateWindow()
    dialog.edit.setFocus()
    QTest.qWait(1)

    dialog.edit.textCursor().insertText("Twice as long as it should be.")
    assert services.document.text(step.id, MODULE_ID) == "Twice as long as it should be."

    press(dialog, Qt.Key.Key_Z)
    assert services.document.text(step.id, MODULE_ID) == ""
    assert dialog.edit.toPlainText() == ""

    press(
        dialog,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert services.document.text(step.id, MODULE_ID) == "Twice as long as it should be."
    assert dialog.edit.toPlainText() == "Twice as long as it should be."

    dialog.dispose()


def _dialogs_handed_the_undo_stack():
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(isinstance(b, ast.Name) and b.id == "QDialog" for b in node.bases):
                continue
            init = next(
                (n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"),
                None,
            )
            if init is None:
                continue
            arguments = list(init.args.args) + list(init.args.kwonlyargs)
            if any(
                argument.annotation is not None
                and "UndoService" in ast.unparse(argument.annotation)
                for argument in arguments
            ):
                yield path, node


def test_every_dialog_handed_the_undo_stack_carries_its_keys():
    """The rule, where a reader will meet it: a dialog that edits the document is a
    surface the user undoes in, and the menu bar cannot reach it."""
    missing = [
        f"{path.relative_to(SRC)}:{node.lineno} {node.name}"
        for path, node in _dialogs_handed_the_undo_stack()
        if "install_undo_keys" not in ast.unparse(node)
    ]
    assert not missing, "dialogs handed an UndoService but not install_undo_keys: " + str(missing)
