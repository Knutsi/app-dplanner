"""The rulebook's shape: a core small enough to load every time, and area files that load.

`CLAUDE.md` is the core; each `.claude/rules/<area>.md` carries the rules about one area, and
Claude Code loads it when a file its `paths:` name is read. A glob that names nothing is a rule
nobody is ever handed, and a module no area claims is one whose rules nobody finds, so both are
asserted here — over the parser `scripts/rules.py` answers with. ARCHITECTURE.md's *The rulebook
is loaded by where you work* has the reasoning.
"""

import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest
from scripts import rules

CORE = rules.ROOT / "CLAUDE.md"
CORE_BUDGET = 32 * 1024
SKILL = rules.ROOT / ".claude" / "skills" / "suite-crash" / "SKILL.md"

# Module packages no area file claims, on purpose. A name goes here only with its reason.
UNSCOPED: tuple[str, ...] = ()


def repository_files() -> list[PurePosixPath]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=rules.ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [PurePosixPath(name) for name in listed.stdout.splitlines()]


def test_the_core_stays_small_enough_to_load_every_time() -> None:
    size = len(CORE.read_bytes())
    assert size <= CORE_BUDGET, (
        f"CLAUDE.md is {size} bytes, over its {CORE_BUDGET}: a rule about one area belongs in "
        "that area's .claude/rules/ file, and the core gains a rule only by trimming one"
    )


def test_every_area_file_names_its_area_and_what_it_governs() -> None:
    areas = rules.area_files()
    assert areas
    assert all(area.heading and area.globs for area in areas)


def test_every_glob_names_a_file() -> None:
    files = repository_files()
    dead = [
        f"{area.path.name}: {pattern}"
        for area in rules.area_files()
        for pattern in area.patterns()
        if not any(file.full_match(pattern) for file in files)
    ]
    assert dead == []


def test_every_module_package_is_claimed_by_an_area() -> None:
    modules = rules.ROOT / "src" / "dplanner" / "modules"
    packages = sorted(path.name for path in modules.iterdir() if (path / "__init__.py").is_file())
    areas = rules.area_files()
    unclaimed = [
        name
        for name in packages
        if name not in UNSCOPED
        and not any(area.covers(f"src/dplanner/modules/{name}/__init__.py") for area in areas)
    ]
    assert unclaimed == []


def test_the_core_indexes_exactly_the_area_files() -> None:
    text = CORE.read_text(encoding="utf-8")
    section = text[text.index("## Rules by area") :]
    section = section[: section.index("\n## ", 1)]
    indexed = set(re.findall(r"^\| `([\w-]+\.md)` \|", section, re.MULTILINE))
    assert indexed == {area.path.name for area in rules.area_files()}


@pytest.mark.parametrize("path", [".claude/rules/canvas.md", ".claude/skills/suite-crash/SKILL.md"])
def test_git_carries_the_rulebook_into_every_worktree(path: str) -> None:
    ignored = subprocess.run(["git", "check-ignore", "--quiet", path], cwd=rules.ROOT)
    assert ignored.returncode == 1, f"{path} is git-ignored, so no worktree would carry it"


def test_the_crash_skill_says_when_to_reach_for_it() -> None:
    front = SKILL.read_text(encoding="utf-8").split("---\n")[1]
    assert re.search(r"^name: suite-crash$", front, re.MULTILINE)
    assert re.search(r"^description: .*SIGSEGV", front, re.MULTILINE)


def governing_names(path: str) -> set[str]:
    return {area.path.name for area in rules.governing([path])}


def test_a_path_is_handed_the_areas_that_govern_it() -> None:
    assert "canvas.md" in governing_names("src/dplanner/modules/project_editor/look.py")
    assert governing_names("src/dplanner/cli/lint.py") == {"cli.md"}
    assert governing_names("README.md") == set()


def test_a_brace_glob_is_every_alternative_in_order() -> None:
    assert rules.expand("a/{b,c}/x_{1,2}.py") == [
        "a/b/x_1.py",
        "a/b/x_2.py",
        "a/c/x_1.py",
        "a/c/x_2.py",
    ]


def test_front_matter_in_any_other_shape_is_refused(tmp_path: Path) -> None:
    area = tmp_path / "area.md"
    area.write_text("---\npaths: src/**\n---\n\n# Area\n", encoding="utf-8")
    with pytest.raises(ValueError, match="front matter"):
        rules.parse(area)
