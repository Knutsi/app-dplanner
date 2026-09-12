"""Render Debug ▸ Design Example in the dark and the light theme, to PNG.

    uv run python scripts/render_design_example.py --out docs/screenshots/f1-design-example

The images are the design system as rendered — what a pull request that touches a surface
shows beside its own screenshots, and what ``docs/screenshots/f1-design-example/`` keeps for
the next developer. Nothing here reads a library: the two surfaces are built directly over
their sample data, once per theme, and the widgets are sized here because the offscreen
screen is smaller than a desktop's.
"""

import argparse
import os
import sys
from pathlib import Path

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.framework.context import ContextService
from dplanner.framework.debounce import DebounceService
from dplanner.framework.theme_service import ThemeService
from dplanner.modules.debug.design_example import (
    DesignExampleActivity,
    DesignExampleDialog,
)
from dplanner.theme import apply_theme
from dplanner.theme.providers import BUILTIN
from dplanner.theme.themes import DARK, LIGHT, Theme

DIALOG_SIZE = (760, 800)
TABLE_SIZE = (900, 520)


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


def render(app: QApplication, theme: Theme, out: Path) -> None:
    apply_theme(app, theme)
    debounce = DebounceService()

    dialog = DesignExampleDialog(debounce)
    dialog.resize(*DIALOG_SIZE)
    dialog.show()
    save(dialog, out, "dialog", theme, app)
    dialog.refuse_switch.setChecked(True)
    save(dialog, out, "dialog-refused", theme, app)
    dialog.refuse_switch.setChecked(False)
    dialog.change_button.click()  # The demo debouncer owes a run: the glyph turns.
    save(dialog, out, "dialog-working", theme, app)
    debounce.flush_all()
    discard(dialog)

    service = ThemeService(app, (BUILTIN,))
    activity = DesignExampleActivity(ContextService(), debounce, service)
    page = activity.widget
    page.resize(*TABLE_SIZE)
    page.show()
    save(page, out, "table", theme, app)
    table = activity.table
    table.selectRow(2)
    QTest.mouseMove(table.viewport(), table.visualRect(table.model().index(4, 1)).center())
    save(page, out, "table-selected", theme, app)
    activity.filter.showPopup()
    settle(app)
    popup = activity.filter.view().window()
    save(popup, out, "dropdown", theme, app)
    activity.filter.hidePopup()
    activity.empty_action.trigger()
    debounce.flush_all()
    save(page, out, "table-empty", theme, app)
    activity.close()
    discard(page)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots/f1-design-example"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    for theme in (DARK, LIGHT):
        render(app, theme, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
