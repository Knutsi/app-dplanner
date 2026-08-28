"""Where per-user, per-machine configuration lives — without Qt.

The GUI keeps its preferences in QSettings, but anything the CLI must also read cannot:
``cli/`` loads no graphics stack. This is the Qt-free per-user config location FORMAT.md
reserves for exactly that case. The project library file is the first resident.
"""

import os
import sys
from pathlib import Path


def config_dir(app: str = "dplanner") -> Path:
    """The per-user configuration directory for ``app``, following each platform's rule.

    Linux honours ``$XDG_CONFIG_HOME`` (default ``~/.config``); Windows uses ``%APPDATA%``;
    macOS uses ``~/Library/Application Support``. The directory is not created here —
    writers create it, readers treat absence as "nothing configured yet".
    """
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", "") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", "") or (Path.home() / ".config"))
    return base / app
