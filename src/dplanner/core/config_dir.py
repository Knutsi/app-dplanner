"""Where per-user, per-machine configuration lives — without Qt.

The GUI keeps its preferences in QSettings, but anything the CLI must also read cannot:
``cli/`` loads no graphics stack. This is the Qt-free per-user config location FORMAT.md
reserves for exactly that case. The project library file is the first resident.
"""

import os
import sys
from pathlib import Path

# Names the directory outright: a test suite or a throwaway check points it elsewhere
# without moving the rest of the user's configuration (git's own is under XDG too).
OVERRIDE_ENV = "DPLANNER_CONFIG_DIR"


def config_dir(app: str = "dplanner") -> Path:
    """The per-user configuration directory for ``app``, following each platform's rule.

    ``$DPLANNER_CONFIG_DIR`` wins when set. Otherwise Linux honours ``$XDG_CONFIG_HOME``
    (default ``~/.config``); Windows uses ``%APPDATA%``; macOS uses ``~/Library/Application
    Support``. The directory is not created here — writers create it, readers treat absence
    as "nothing configured yet".
    """
    if override := os.environ.get(OVERRIDE_ENV, ""):
        return Path(override)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", "") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", "") or (Path.home() / ".config"))
    return base / app
