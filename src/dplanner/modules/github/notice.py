"""A launch-time warning when the GitHub CLI is missing.

The dialog is advisory and dismissable for good: its "Show next time" checkbox persists
through :mod:`~dplanner.framework.user_config`, and a process-wide flag keeps a workspace
switch (which re-runs every module's ``register()``) from repeating it. It uses
``box.open()``, never ``exec()`` — a nested modal loop can deadlock headless tests.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from dplanner.framework.user_config import get_global, set_global
from dplanner.modules.github.aspect import MODULE_ID

WARN_KEY = "warn_missing_gh"

# One warning per process, however many workspaces get opened.
_warned_this_process = False


def warn_enabled() -> bool:
    return bool(get_global(MODULE_ID, WARN_KEY, True))


def set_warn_enabled(enabled: bool) -> None:
    set_global(MODULE_ID, WARN_KEY, bool(enabled))


def maybe_warn(parent: QWidget | None, installed: Callable[[], bool]) -> QMessageBox | None:
    """Show the missing-gh warning when it is due; returns the box so tests can drive it."""
    global _warned_this_process
    if _warned_this_process or not warn_enabled() or installed():
        return None
    _warned_this_process = True

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("GitHub CLI Not Found")
    box.setText("The GitHub CLI (gh) is not installed.")
    box.setInformativeText(
        "Pull-request status and repository auto-fill need it. "
        "Install it from https://cli.github.com and sign in with `gh auth login`."
    )
    checkbox = QCheckBox("Show next time", box)
    checkbox.setChecked(True)
    box.setCheckBox(checkbox)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    box.finished.connect(lambda _result: set_warn_enabled(checkbox.isChecked()))
    box.open()
    return box
