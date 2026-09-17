"""The version is one string, and the build reads it from where the application does.

``identity.APP_VERSION`` is the source; ``pyproject.toml`` declares ``dynamic = ["version"]``
and hands hatchling a regex to read that line. The number was written out twice before, and
two copies of a version drift the day somebody bumps one of them — a build reporting 0.1.0
against a tag that says 0.2.0 is a support question with no answer.

The failure this guards is quiet. Reformatting ``identity.py`` — a different quote, a dropped
``Final``, ruff's own hand — stops the pattern matching, and hatchling then fails the build
with a message about a version it could not find, on the release runner, at tag time. Here it
fails on the machine that made the change. No build runs: the pattern is applied to the file
exactly as hatchling would.
"""

import re
import tomllib
from pathlib import Path

from dplanner.identity import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def hatch_version() -> dict[str, str]:
    tool = pyproject()["tool"]
    assert isinstance(tool, dict)
    source = tool["hatch"]["version"]
    assert isinstance(source, dict)
    return source


def test_the_project_version_is_dynamic() -> None:
    project = pyproject()["project"]
    assert isinstance(project, dict)
    assert "version" not in project, (
        "pyproject.toml carries a static version again — it is identity.APP_VERSION's, and "
        "a second copy is one that can disagree with the tag"
    )
    assert project["dynamic"] == ["version"]


def test_hatchling_reads_the_version_the_application_reads() -> None:
    source = hatch_version()
    read = ROOT / source["path"]
    assert read == ROOT / "src" / "dplanner" / "identity.py"
    found = re.search(source["pattern"], read.read_text(encoding="utf-8"))
    assert found is not None, (
        f"[tool.hatch.version] pattern no longer matches {source['path']}: the build would "
        "fail at tag time. Keep the APP_VERSION line's shape, or update the pattern with it."
    )
    assert found.group("version") == APP_VERSION
