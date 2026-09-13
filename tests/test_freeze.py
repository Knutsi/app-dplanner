"""The frozen build ships every file the application reads.

``freeze/datas.py`` is the manifest PyInstaller is handed. These tests hold it to one rule —
*a data file lands at its own package path* — because that is the single thing that makes
both of the application's resource styles work at once: ``importlib.resources.files`` asks the
frozen importer for a package's directory, and ``Path(__file__).parent`` inside a frozen
module resolves to the same one. A glyph, a stylesheet or a shipped markdown file that does
not land there is not missing at build time and not missing in the rest of this suite; it is
missing the first time somebody opens the window on a machine with no checkout.

No PyInstaller import here on purpose: the rule is checkable on every machine that runs the
suite, including every machine that never builds.
"""

from pathlib import Path

from freeze.datas import PACKAGE, package_datas, shipped_files

# Where the application reads a non-Python file, one entry per call site, so a move fails here
# rather than at somebody's first launch. The comment is the reader.
READ_SITES = (
    "dplanner/theme/theme.qss",                # theme/__init__.py:35    resources.files
    "dplanner/theme/glyphs/spec.svg",          # theme/icons.py:94       GLYPH_DIR.joinpath
    "dplanner/theme/glyphs/LICENSE",           # Help ▸ About names the set; the MIT notice
    "dplanner/assets/icons/dplanner-256.png",  # assets/__init__.py:17   files("dplanner.assets")
    "dplanner/cli/skill_preamble.md",          # cli/skill.py:45         Path(__file__).parent
    "dplanner/cli/shaping.md",                 # cli/shaping.py:24       Path(__file__).parent
    "dplanner/cli/report/report.css",          # cli/report/website.py:141
    "dplanner/cli/report/report.js",           # cli/report/page.py:308
    "dplanner/cli/report/about.md",            # cli/report/page.py:308
)


def destinations() -> dict[str, str]:
    """Every manifest entry as the path it lands at → the file it came from."""
    return {f"{dest}/{Path(source).name}": source for source, dest in package_datas()}


def test_every_non_python_file_under_the_package_is_shipped():
    """A new glyph, a new report asset or a new shipped document travels without anybody
    remembering to add it — and cannot be dropped by narrowing the manifest to a list."""
    expected = {f"dplanner/{path.relative_to(PACKAGE).as_posix()}" for path in shipped_files()}
    assert destinations().keys() == expected
    assert len(package_datas()) == len(expected)  # One entry per file, and nothing twice.


def test_each_file_lands_at_its_own_package_path():
    """The rule. ``resources.files("dplanner.theme")`` and ``Path(__file__).parent`` inside
    ``dplanner/cli/`` have to agree about where a package's files are, and they only do while
    every destination mirrors its source."""
    for source, destination in package_datas():
        relative = Path(source).relative_to(PACKAGE).parent
        assert destination == (Path("dplanner") / relative).as_posix()


def test_every_place_the_application_reads_from_is_carried():
    shipped = destinations()
    assert [site for site in READ_SITES if site not in shipped] == []


def test_no_python_file_is_shipped_as_data():
    """Modules belong in the archive. A ``.py`` copied in beside it is a second, stale copy of
    the same module, and which one wins is the importer's business rather than ours."""
    assert [source for source, _ in package_datas() if source.endswith(".py")] == []
