"""The rulebook's shape: a core small enough to load every time, and area files that load.

`CLAUDE.md` is the core; each `.claude/rules/<area>.md` carries the rules about one area, and
Claude Code loads it when a file its `paths:` name is read. A glob that names nothing is a rule
nobody is ever handed, and a module no area claims is one whose rules nobody finds, so both are
asserted here — over the parser `scripts/rules.py` answers with. The reasoning behind each area's
rules is `docs/architecture/<area>.md`, and a pointer into it is held to a heading that exists.
`docs/architecture/core.md`'s *The rulebook is loaded by where you work* has the reasoning.
"""

import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest
from scripts import rules

CORE = rules.ROOT / "CLAUDE.md"
CORE_BUDGET = 32 * 1024
SKILL = rules.ROOT / ".claude" / "skills" / "suite-crash" / "SKILL.md"
REASONING = rules.ROOT / "docs" / "architecture"
DIVERGENCES = rules.ROOT / "NOTES-FOR-APPFRAME.md"

# Dated records: they cite the documents as they stood when written, and are never rewritten.
RECORDS = (
    "docs/research/",
    "docs/proposals/",
    "docs/towards-v2/",
    "docs/architecture-state/",
    "docs/history/",
)
POINTER = re.compile(r"`{0,2}(docs/architecture/[\w-]+\.md|ARCHITECTURE\.md)`{0,2}'s\s+\*([^*]+)\*")

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
    assert "canvas.md" in governing_names("src/dplanner/modules/canvas/look.py")
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


def live_texts() -> list[tuple[PurePosixPath, str]]:
    texts = []
    for file in repository_files():
        if str(file).startswith(RECORDS) or file.suffix not in {".md", ".py", ".html", ".toml"}:
            continue
        path = rules.ROOT / file
        if path.is_file():
            texts.append((file, path.read_text(encoding="utf-8")))
    return texts


def headings(text: str) -> set[str]:
    """What a pointer may name: a heading, or the bold lead that opens a paragraph or a bullet."""
    titles = re.findall(r"^#{2,4} (.+)$", text, re.MULTILINE)
    leads = re.findall(r"^(?:- )?\*\*([^*]+?)[.:]?\*\*", text, re.MULTILINE)
    return {" ".join(title.split()) for title in titles + leads}


def cited_title(raw: str) -> str:
    """A title as cited, unwrapped: a pointer in a comment continues on a `# ` line."""
    return " ".join(re.sub(r"\n\s*(#|//)?", " ", raw).split())


def test_every_pointer_into_the_reasoning_names_a_heading_that_exists() -> None:
    known = {
        f"docs/architecture/{p.name}": headings(p.read_text(encoding="utf-8"))
        for p in REASONING.glob("*.md")
    }
    broken = [
        f"{file}: {target}'s *{cited_title(title)}*"
        for file, text in live_texts()
        for target, title in POINTER.findall(text)
        if not any(heading.startswith(cited_title(title)) for heading in known.get(target, ()))
    ]
    assert broken == [], (
        "a section is cited as `docs/architecture/<area>.md`'s *Its heading*, or its opening "
        "words; ARCHITECTURE.md is only the index and has no sections to cite"
    )


def test_a_pointer_between_reasoning_files_names_a_heading_that_exists() -> None:
    """Inside `docs/architecture/`, `canvas.md`'s *Title* names a sibling or its rules file."""
    sibling = re.compile(r"(?<![/\w])`([a-z][\w-]*)\.md`'s\s+\*([^*]+)\*")
    rules_dir = rules.ROOT / ".claude" / "rules"
    broken = []
    for path in REASONING.glob("*.md"):
        for stem, title in sibling.findall(path.read_text(encoding="utf-8")):
            known = set()
            for candidate in (REASONING / f"{stem}.md", rules_dir / f"{stem}.md"):
                if candidate.is_file():
                    known |= headings(candidate.read_text(encoding="utf-8"))
            if not any(heading.startswith(cited_title(title)) for heading in known):
                broken.append(f"{path.name}: {stem}.md's *{cited_title(title)}*")
    assert broken == []


def test_the_reasoning_has_one_file_per_area() -> None:
    stems = {p.stem for p in REASONING.glob("*.md")}
    assert stems == {area.path.stem for area in rules.area_files()} | {"core", "decisions"}


def test_every_divergence_is_filed_under_a_file_that_exists() -> None:
    text = DIVERGENCES.read_text(encoding="utf-8")
    filed = re.findall(r"^## `([^`]+)`$", text, re.MULTILINE)
    assert filed
    package = rules.ROOT / "src" / "dplanner"
    assert [name for name in filed if not (package / name).exists()] == []
    assert filed == sorted(filed, key=lambda name: (not name.startswith("framework/"), name))
