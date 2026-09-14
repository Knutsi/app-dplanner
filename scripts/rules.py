"""Which of the rulebook's area files govern a path, or everything a branch changed.

    uv run python scripts/rules.py for src/dplanner/modules/project_editor/look.py
    uv run python scripts/rules.py diff              # since the merge base with origin/main
    uv run python scripts/rules.py diff main --names

``CLAUDE.md`` is the core every session loads. Each ``.claude/rules/<area>.md`` names the files
it governs in a ``paths:`` list, and Claude Code loads it when one of those files is read. This
gives the same answer to everything that trigger misses — a plan written before any file is
read, an edit made through the shell, a file that does not exist yet, an agent CLI that never
reads ``.claude/rules/`` — and it is the one parser ``tests/test_rules.py`` holds the files to.
Searching the rules is ``grep``'s job, not this script's.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / ".claude" / "rules"
DEFAULT_BASE = "origin/main"

# The one front-matter shape: a `paths:` list of quoted globs and nothing else, so what this
# script matches is exactly what Claude Code loads on.
_FRONT = re.compile(r'\A---\npaths:\n((?:  - "[^"\n]+"\n)+)---\n')
_GLOB = re.compile(r'  - "([^"\n]+)"')
_BRACES = re.compile(r"\{([^{}]*)\}")


def expand(glob: str) -> list[str]:
    """Every pattern a brace glob stands for, in order: ``a/{b,c}.py`` is two."""
    match = _BRACES.search(glob)
    if match is None:
        return [glob]
    head, tail = glob[: match.start()], glob[match.end() :]
    return [each for alt in match.group(1).split(",") for each in expand(head + alt + tail)]


@dataclass(frozen=True)
class AreaRules:
    path: Path
    heading: str
    globs: tuple[str, ...]
    body: str

    def patterns(self) -> list[str]:
        return [pattern for glob in self.globs for pattern in expand(glob)]

    def covers(self, relative: str) -> bool:
        target = PurePosixPath(relative)
        return any(target.full_match(pattern) for pattern in self.patterns())


def parse(path: Path) -> AreaRules:
    text = path.read_text(encoding="utf-8")
    front = _FRONT.match(text)
    if front is None:
        raise ValueError(
            f"{path.name}: the front matter must be a `paths:` list of quoted globs, one per line"
        )
    body = text[front.end() :].lstrip("\n")
    heading = body.partition("\n")[0]
    if not heading.startswith("# "):
        raise ValueError(f"{path.name}: the rules must open with a `# ` heading naming the area")
    return AreaRules(path, heading.removeprefix("# "), tuple(_GLOB.findall(front.group(1))), body)


def area_files(rules: Path = RULES) -> list[AreaRules]:
    return [parse(path) for path in sorted(rules.glob("*.md"))]


def governing(paths: Iterable[str], rules: Path = RULES) -> list[AreaRules]:
    wanted = list(paths)
    return [area for area in area_files(rules) if any(area.covers(path) for path in wanted)]


def repository_relative(path: str) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return PurePosixPath(path).as_posix()


def changed_since(base: str) -> list[str]:
    """Every file changed since ``base``'s merge base: committed, uncommitted and untracked."""

    def git(*args: str) -> list[str]:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
        return done.stdout.splitlines()

    fork = git("merge-base", base, "HEAD")[0]
    untracked = git("ls-files", "--others", "--exclude-standard")
    return sorted({*git("diff", "--name-only", fork), *untracked})


def report(areas: list[AreaRules], names_only: bool) -> str:
    if not areas:
        return "No area file governs these paths; CLAUDE.md's core is their whole rulebook.\n"
    if names_only:
        return "".join(f".claude/rules/{area.path.name} — {area.heading}\n" for area in areas)
    return "\n".join(f"== .claude/rules/{area.path.name}\n\n{area.body}" for area in areas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rules.py", description=__doc__.partition("\n")[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    for_paths = verbs.add_parser("for", help="the area files that govern these paths")
    for_paths.add_argument("paths", nargs="+")
    for_diff = verbs.add_parser("diff", help="the area files that govern what changed since BASE")
    for_diff.add_argument("base", nargs="?", default=DEFAULT_BASE)
    for verb in (for_paths, for_diff):
        verb.add_argument("--names", action="store_true", help="name the files, not their rules")
    args = parser.parse_args(argv)
    if args.verb == "for":
        paths = [repository_relative(path) for path in args.paths]
    else:
        paths = changed_since(args.base)
    sys.stdout.write(report(governing(paths), args.names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
