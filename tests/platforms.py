"""What the suite needs to say about the machine it runs on — and nothing more.

Three things, kept here rather than at their call sites so the answer is the same everywhere
and a fourth case has somewhere obvious to go.

``set_home`` exists because ``monkeypatch.setenv("HOME", …)`` does not move ``Path.home()``
on Windows: ``ntpath.expanduser`` reads ``USERPROFILE`` first and never looks at ``HOME``, so
a test that redirected only ``HOME`` would quietly assert against the developer's real home
directory. ``tests/cli/test_entry.py`` already sets ``APPDATA`` beside ``HOME`` for the same
reason; this is that, complete and in one place.

The two markers are the suite's only platform marks, and CLAUDE.md's rule says why: a mark
belongs on a test whose whole subject is a platform's own concept, or a capability the host
may not have. Both are phrased as capabilities rather than platforms — ``SYMLINKS`` switches
itself on when a Windows developer turns Developer Mode on, which a ``sys.platform`` check
never would.
"""

import os
import tempfile
from pathlib import Path

import pytest

POSIX_MODE_BITS = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX mode bits: Windows has none, and chmod cannot set an execute bit there",
)


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as directory:
        try:
            Path(directory, "link").symlink_to(Path(directory))
        except (OSError, NotImplementedError):
            return False
    return True


SYMLINKS = pytest.mark.skipif(
    not _can_symlink(),
    reason="making a symlink needs Developer Mode or an elevated shell on Windows",
)


def set_home(monkeypatch, home: Path) -> Path:
    """Move ``Path.home()`` and every per-user directory derived from it to ``home``.

    Every variable any platform's ``expanduser`` or ``core/config_dir.py`` consults, so a
    test that redirects the home directory redirects all of it and nothing leaks into the
    developer's own.
    """
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # What ntpath's expanduser actually reads.
    monkeypatch.delenv("HOMEDRIVE", raising=False)  # Consulted before HOME where they exist.
    monkeypatch.delenv("HOMEPATH", raising=False)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    return home
