"""What the frozen build carries beside the code: every file under ``src/dplanner`` that is
not Python.

**One rule, and both of the application's readers depend on it: a data file lands at its own
package path.** The shipped files are read two ways —

* ``importlib.resources.files(...)`` — ``assets/__init__.py``, ``theme/icons.py``,
  ``theme/__init__.py``, ``cli/report/``;
* ``Path(__file__).parent / name`` — ``cli/skill.py``, ``cli/shaping.py``.

Under PyInstaller the first is served by the frozen importer's resource reader and the second
by the ``__file__`` PyInstaller stamps on each frozen module, and **both resolve to the same
directory**. So a file's destination is its own directory relative to the package, and nothing
has to be decided per file. Get that wrong for one file and it is not missing at build time
and not missing in the suite; it is missing the first time somebody opens the window on a
machine with no checkout.

Walked rather than listed by hand, because a hand-written list goes stale one glyph at a time.
``tests/test_freeze.py`` holds the walk to the rule.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "dplanner"
DESTINATION_ROOT = "dplanner"


def shipped_files() -> list[Path]:
    """Every non-Python file the package ships, in a stable order."""
    return [
        path
        for path in sorted(PACKAGE.rglob("*"))
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
    ]


def package_datas() -> list[tuple[str, str]]:
    """PyInstaller ``datas``: ``(source file, destination directory)``, one entry per file.

    The destination is written POSIX-style whatever host builds, so a Windows build and a
    Linux build lay the bundle out identically.
    """
    return [
        (str(path), (Path(DESTINATION_ROOT) / path.relative_to(PACKAGE).parent).as_posix())
        for path in shipped_files()
    ]
