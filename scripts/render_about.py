"""Render Help ▸ About DPlanner in the dark and the light theme, to PNG.

    uv run python scripts/render_about.py --out docs/screenshots/s7-about

What this is and what it stands on, in one dialog: the name and version, then a row per
component with the version and licence read from the installed distribution's own metadata.
Re-run it after changing the dialog or the list, and commit the result.
"""

import argparse
import os
import sys
from pathlib import Path

# A shell that presets the platform would put every render on the desktop.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

from dplanner.modules.appshell.about import ABOUT_SIZE, AboutDialog
from dplanner.theme import apply_theme
from dplanner.theme.themes import DARK, LIGHT, Theme


def settle(app: QApplication) -> None:
    for _ in range(3):
        app.processEvents()


def discard(widget: QWidget) -> None:
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def render(app: QApplication, theme: Theme, out: Path) -> None:
    apply_theme(app, theme)
    dialog = AboutDialog()
    dialog.show()
    # The offscreen screen is smaller than a desktop's, and a framed dialog is clamped to a
    # share of it — so the size it would open at on a real screen is asked for here.
    dialog.resize(*ABOUT_SIZE)
    settle(app)
    path = out / f"about-{theme.name}.png"
    dialog.grab().save(str(path), "PNG")
    print(path)
    discard(dialog)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="directory for the PNGs")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    for theme in (DARK, LIGHT):
        render(app, theme, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
