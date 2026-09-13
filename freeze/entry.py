"""The frozen build's entry point: the console ``dplanner`` and the windowed ``dpw``, in one
script.

``pyproject.toml`` declares two entry points and a wheel install generates two launchers from
them. A PyInstaller build has to make the two executables itself, and on Windows the only
difference between them is the subsystem bit the linker writes — so rather than scan the
dependency tree twice for two one-line scripts, both executables share this script and read
which of the two they are from their own filename.

``dpw`` is not a new convention here: ``cli/main.py`` owns the spelling (``WINDOW_SHORTCUT``),
``cli/desktop.py`` finds the executable by it, and the Start Menu shortcut opens it. Renaming
either executable in ``dplanner.spec`` therefore changes behaviour, which is why the
comparison is against the constant rather than a literal.
"""

import sys
from pathlib import Path

from dplanner.cli.main import WINDOW_SHORTCUT
from dplanner.entry import main, window_main

if __name__ == "__main__":
    windowed = Path(sys.executable).stem.lower() == WINDOW_SHORTCUT
    raise SystemExit(window_main() if windowed else main())
