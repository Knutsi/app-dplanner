"""Layering rules, enforced.

The architecture is ``core`` → ``domain`` → ``planning`` → ``cli`` → ``framework`` →
``modules`` → the composition root (``modules/__init__.py``) → ``app``. These tests parse
every source file's imports with the standard library's ``ast`` — no Qt is loaded, no import
is executed — and fail with the offending file and line when a rule is broken.

``TYPE_CHECKING``-only imports count on purpose: type coupling is still coupling, and an
architecture that holds only at runtime is one refactor from not holding at all.

The rules, in prose (see also CLAUDE.md):

1. ``core/`` imports no Qt and nothing from the rest of the application. It is the bottom
   layer, and it is what every application built from this template shares.
2. ``domain/`` imports no Qt, and imports ``core`` only. Your model must stay testable with
   plain pytest, and must never depend on the machinery that displays it.
3. ``framework/`` never imports ``modules`` or ``app``. It may use ``core``, ``domain``,
   ``planning`` and ``theme``.
4. A module reaches another only through its ``aspect.py`` (facts) or ``workflows.py``
   (complete workflows), at the top of that package, and both are headless — checked by
   following everything they import, not by their names. A ``workflows.py`` builds and never
   persists, so it imports no ``domain.store`` itself. Only ``modules/__init__.py`` may import
   the rest of a module — except a package with no ``module.py``, which registers nothing and
   is surface all through (``agent_briefing``, a harness): any of its files may be imported,
   and every one is held headless the same way.
5. Modules never import ``AppServices``, the builder, or the concrete window — they receive
   typed ``Deps`` objects and reach the window through the capability protocols.
6. ``app.py`` and ``entry.py`` never reach into a module subpackage; they may import the
   composition root.
7. ``cli/`` imports no Qt and nothing above ``planning/``, and a module's ``cli.py`` and
   ``aspect.py`` are the same: importable without a graphics stack. The CLI is how an agent
   drives this application, and it has to start in milliseconds on a machine with no GUI
   libraries at all.
8. Only ``core/storage/`` and the composition root may import a *concrete* storage provider.
   Everything else depends on the protocols — which is what makes "swap the storage system"
   true rather than aspirational.
9. ``theme/`` is a leaf: it imports ``core`` at most, and importing the package loads no Qt —
   a theme provider module reads the themes, the providers and the Omarchy mapping without
   a graphics stack, and the Qt half is imported inside ``apply_theme``.
10. ``planning/`` imports no Qt and only ``core`` and ``domain``, and ``domain/`` never
    imports it. The planning model — status, readiness, the schedule — sits on the graph and
    under every feature, so a feature can read it and it can read no feature.
11. The module import graph is acyclic; a failure names the cycle, edge by edge.
12. Two counts may only fall: the composition root's lines, and the built-in commands pushed
    or applied directly outside a ``workflows.py``. They are ceilings, lowered by hand.
13. The ids a module stores its data under are pinned: a package may move, its ids may not.
14. The aspects ``planning/`` interprets are listed: admitting one is a reviewed diff.
15. A file's name says what it holds: a tab is in ``activity.py`` (or ``<x>_activity.py``), a
    modal in ``dialog.py`` (or ``<x>_dialog.py``), a ``QGraphicsScene`` in ``scene.py``, and
    no file in a module package is called ``view.py`` or ``<x>_view.py``.

`docs/architecture/core.md`'s *What holds the tier and the workflows in place* has the reasoning for
rules 4 and 11 to 13.

**When one of these fails, fix the dependency direction, not the test.** Every rule has a
supported way to get what the shortcut wanted: a capability protocol, a typed callback on
your ``Deps``, or a registry.
"""

import ast
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "dplanner"
PACKAGE = SRC.name

QT_PACKAGES = ("PySide6", "shiboken6")

# The file roles that load no Qt in every module package: what the CLI reaches (verbs, the
# aspect and workflow surface, location roles, checks, a report's source, a harness) and
# the one a contract keeps Qt-free without the CLI (a theme provider's ``themes.py``).
HEADLESS_ROLES = (
    "cli.py",
    "workflows.py",
    "aspect.py",
    "roles.py",
    "checks.py",
    "harness.py",
    "report.py",
    "themes.py",
)
# Every other file the CLI reaches, by package and its path inside it. Checked by path, so a
# name means one file: if the composition root imports a file at CLI time, it belongs here,
# and a listed path that no longer exists fails the suite rather than silently leaving the rule.
HEADLESS_FILES: dict[str, tuple[str, ...]] = {
    "agent_briefing": ("prompt.py",),
    # A step leaving its squad, however it leaves: its worker stopped.
    "agent_claims": ("ownership.py",),
    "agent_launch": ("availability.py", "launch.py", "launcher.py", "profiles.py"),
    # Answering a question and resuming its run: the `question answer` verb and the card.
    "agent_questions": ("inbox.py",),
    # Reads a run's usage back into the ledger: the wrapper script's `dplanner` call.
    "agent_usage": ("harvest.py",),
    # The run supervisor: a package with no window half, reached by `agent supervise`.
    "agent_supervisor": ("supervisor.py",),
    # A branch stretch's run plan, and the edits it makes.
    "branches": ("edits.py", "plan.py"),
    "canvas": (
        "clipboard/clip.py",
        "geometry.py",
        "layouts/named.py",
        "layouts/placement.py",
        "layouts/positions.py",
        "layouts/sorts.py",
        "look.py",
        "marks.py",
        "stacks/edits.py",
        "stacks/stack.py",
    ),
    # Where the coverage trace's facts come from, and the trace.
    "coverage": ("readers.py", "trace.py"),
    "dictation_whisper": ("dictation.py",),
    "docs": ("collect.py", "prompt.py"),
    "github": ("gh.py",),
    "library": ("membership.py",),
    "notes": ("migrate.py",),
    "openai": ("dictation.py",),
    "schedule": (
        "assumptions.py",
        "landings.py",
        "progress.py",
        # What the Time tab shows, as data: the report reads it too.
        "present.py",
        # The simulator: a script and the tests play it with no graphics stack.
        "simulation/accuracy.py",
        "simulation/edits.py",
        "simulation/frames.py",
        "simulation/replay.py",
        "simulation/rng.py",
        "simulation/sample.py",
        "simulation/scenarios.py",
        "simulation/simulate.py",
        "simulation/timeline.py",
        "simulation/world.py",
    ),
    "spec": ("documents.py", "pdf.py", "sourced.py"),
    "spec_confluence": ("client.py", "convert.py", "source.py"),
    "spec_folder": ("source.py",),
    "spec_git": ("source.py",),
    "step_agent_run": ("runs.py", "terminal.py"),
    "step_order": ("export.py",),
    "step_playbook": ("presets.py",),
    "testing": ("export.py", "filing.py", "format.py", "references.py", "runs.py"),
}


def is_headless(path: Path, root: Path = SRC) -> bool:
    """Whether a module-package file must load no Qt: a role every package's copy of keeps
    Qt-free, or a file its own package lists."""
    package = module_dir_of(path, root)
    if package is None:
        return False
    inside = path.relative_to(root / "modules" / package).as_posix()
    return path.name in HEADLESS_ROLES or inside in HEADLESS_FILES.get(package, ())


CONCRETE_STORAGE = (
    f"{PACKAGE}.core.storage.local",
    f"{PACKAGE}.core.storage.git",
    f"{PACKAGE}.core.storage.github",
    f"{PACKAGE}.core.storage.locations",
)

# Ceilings (rule 12), recorded on 4 October 2026. Lower one by hand when its count falls;
# never raise it.
ROOT_LINES = 3375
DIRECT_COMMANDS = 137

# Every id a module stores data, settings or files under (rule 13). Stored ids are public:
# plans on disk, user settings and the keychain know a module by them.
STORED_IDS = frozenset(
    {
        "agent_at_work",
        "agent_claims",
        "agent_usage",
        "appearance",
        "branch_cut",
        "branch_land",
        "checklist",
        "coverage",
        "dictation",
        "docs",
        "docs_compiled",
        "estimation",
        "feature",
        "github",
        "home",
        "install",
        "library",
        "library_watch",
        "llm",
        "llm_anthropic",
        "llm_openai",
        "notes",
        "problems",
        "progress_history",
        "progression",
        "project_assets",
        "project_editor",
        "projects",
        "reopen_tabs",
        "reporting",
        "settings",
        "shelf",
        "spec",
        "spec_confluence",
        "step_agent_instruction",
        "step_agent_run",
        "step_check",
        "step_description",
        "step_milestone",
        "step_order",
        "step_playbook",
        "step_properties",
        "step_start",
        "step_status",
        "step_ticket",
        "step_wait",
        "testing",
        "time_estimates",
    }
)

# Every id a module once stored under and no longer does (rule 13, FORMAT.md's *Retiring a
# module*). A retired id is never declared again: plans on disk may still carry its files,
# kept untouched as data nobody declares, and a new module under the same name would read
# them as its own.
RETIRED_IDS = frozenset(
    {
        "auto_progress",
        "decisions",
        "review_rounds",
        "step_review",
        "step_estimation",
        "step_feature",
        "step_handoff",
        "step_release",
    }
)

# The aspects planning/ owns (rule 14). An aspect is admitted only when a headless server
# or daemon must interpret it — status, what a step is and its estimate, so far. The list
# growing past about fifteen is the signal that planning/ has become "the important
# aspects": stop and reconsider rather than add.
PLANNING_ASPECTS = frozenset(
    {
        "branch_cut",
        "branch_land",
        "estimation",
        "feature",
        "step_agent_instruction",
        "step_check",
        "step_milestone",
        "step_start",
        "step_status",
        "step_wait",
    }
)


def imported_names(path: Path, root: Path = SRC) -> list[tuple[int, str]]:
    """Absolute names imported by ``path``: (line, dotted-name) pairs.

    Relative imports are resolved against the file's own package, so ``from . import x``
    inside ``dplanner/modules/projects/`` reads as ``dplanner.modules.projects``. A name
    imported *from* a package that is itself a module under ``root`` is recorded too:
    ``from dplanner import planning`` and ``from .. import modules`` import that package as
    surely as ``import dplanner.planning`` does, and a rule that read only the part before
    ``import`` would wave them through. Whether a name is a module is asked of the tree,
    because ``from dplanner.modules import default_modules`` names a function.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    relative_to = path.relative_to(root.parent)
    package_parts = list(relative_to.parts[:-1])
    names: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                anchor = package_parts[: len(package_parts) - (node.level - 1)]
                base = ".".join(anchor + ([node.module] if node.module else []))
            names.append((node.lineno, base))
            names.extend(
                (node.lineno, f"{base}.{alias.name}")
                for alias in node.names
                if _is_module(root.parent.joinpath(*base.split("."), alias.name))
            )
    return names


def _is_module(stem: Path) -> bool:
    return stem.with_suffix(".py").is_file() or (stem / "__init__.py").is_file()


def module_dir_of(path: Path, root: Path = SRC) -> str | None:
    """The module package name for files under ``modules/<name>/``, else None."""
    parts = path.relative_to(root).parts
    if len(parts) >= 2 and parts[0] == "modules":
        return parts[1] if len(parts) >= 3 or parts[1] != "__init__.py" else None
    return None


def collect_violations(root: Path = SRC) -> list[str]:
    """Every rule broken under ``root``, which is the real ``src/dplanner`` unless a test
    hands over a throwaway tree — see :func:`test_the_rules_can_catch_a_violation`."""
    violations: list[str] = []

    def forbid(path: Path, line: int, name: str, rule: str) -> None:
        relative = path.relative_to(root.parent)
        violations.append(f"{relative}:{line}: imports {name!r} — {rule}")

    headless = headless_packages(root)
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        top = parts[0]
        is_composition_root = parts == ("modules", "__init__.py")
        in_storage = parts[:2] == ("core", "storage")

        for line, name in imported_names(path, root):
            # -- rule 7, checked for every file -------------------------------------------
            # app.py chooses a library path, never a provider class. `locations` is the
            # public front door and stays open to everyone.
            may_name_a_provider = (
                in_storage
                or is_composition_root
                or parts in (("app.py",), ("entry.py",))
                or name.endswith(".locations")
            )
            if name in CONCRETE_STORAGE and not may_name_a_provider:
                forbid(path, line, name, "features depend on the storage protocols, not a provider")

            if top == "core":
                if name.startswith(QT_PACKAGES):
                    forbid(path, line, name, "core/ must stay free of Qt imports")
                if name.startswith(
                    (
                        f"{PACKAGE}.domain",
                        f"{PACKAGE}.planning",
                        f"{PACKAGE}.framework",
                        f"{PACKAGE}.modules",
                        f"{PACKAGE}.theme",
                        f"{PACKAGE}.app",
                        f"{PACKAGE}.menus",
                    )
                ):
                    forbid(path, line, name, "core/ is the bottom layer; it imports nothing above")
            elif top == "domain":
                if name.startswith(QT_PACKAGES):
                    forbid(path, line, name, "domain/ must stay free of Qt imports")
                if name.startswith(
                    (
                        f"{PACKAGE}.planning",
                        f"{PACKAGE}.cli",
                        f"{PACKAGE}.framework",
                        f"{PACKAGE}.modules",
                        f"{PACKAGE}.theme",
                        f"{PACKAGE}.app",
                    )
                ):
                    forbid(path, line, name, "domain/ may import core/ only")
            elif top == "planning":
                if name.startswith(QT_PACKAGES):
                    forbid(path, line, name, "planning/ must stay free of Qt imports")
                if name.startswith(f"{PACKAGE}.") and not name.startswith(
                    (f"{PACKAGE}.core", f"{PACKAGE}.domain", f"{PACKAGE}.planning")
                ):
                    forbid(path, line, name, "planning/ imports core/ and domain/ only")
            elif top == "cli":
                if name.startswith(QT_PACKAGES):
                    forbid(path, line, name, "cli/ must stay free of Qt imports")
                if name.startswith(
                    (
                        f"{PACKAGE}.framework",
                        f"{PACKAGE}.modules",
                        f"{PACKAGE}.theme",
                        f"{PACKAGE}.app",
                        f"{PACKAGE}.entry",
                    )
                ):
                    forbid(path, line, name, "cli/ sits above planning/ and below the modules")
            elif top == "framework":
                if name.startswith(f"{PACKAGE}.modules") or name == f"{PACKAGE}.app":
                    forbid(path, line, name, "framework/ never imports modules or the app")
            elif top == "theme":
                if name.startswith(
                    (
                        f"{PACKAGE}.domain",
                        f"{PACKAGE}.cli",
                        f"{PACKAGE}.framework",
                        f"{PACKAGE}.modules",
                        f"{PACKAGE}.app",
                        f"{PACKAGE}.entry",
                        f"{PACKAGE}.menus",
                    )
                ):
                    forbid(path, line, name, "theme/ is a leaf; it imports core at most")
            elif top == "modules":
                if is_composition_root:
                    continue  # The one place allowed to import everything.
                own = module_dir_of(path, root)
                # The headless half of a module. The composition root reaches these through
                # `dplanner.modules`, so one Qt import here would put a graphics stack in
                # every CLI invocation.
                if is_headless(path, root):
                    if name.startswith(QT_PACKAGES):
                        forbid(path, line, name, f"a module's {path.name} loads no Qt")
                    if name.startswith(f"{PACKAGE}.framework"):
                        forbid(path, line, name, f"a module's {path.name} uses core and domain")
                if name.startswith(f"{PACKAGE}.modules."):
                    other, *inside = name.split(".")[2:]
                    on_surface = other in headless or inside in ([], ["aspect"], ["workflows"])
                    if other != own and not on_surface:
                        forbid(
                            path,
                            line,
                            name,
                            "modules reach each other only through aspect.py, workflows.py or a "
                            "package with no module.py",
                        )
                if path.name == "workflows.py" and name.startswith(f"{PACKAGE}.domain.store"):
                    forbid(path, line, name, "a workflow builds a change; its caller persists it")
                if name == f"{PACKAGE}.modules":
                    forbid(path, line, name, "modules never import the composition root")
                bundle = (f"{PACKAGE}.framework.services", f"{PACKAGE}.framework.builder")
                if name.startswith(bundle):
                    forbid(
                        path, line, name, "modules receive typed Deps objects, never AppServices"
                    )
                if name == f"{PACKAGE}.framework.main_window":
                    forbid(path, line, name, "modules use the framework/window.py protocols")
            elif parts in (("app.py",), ("entry.py",)) and name.startswith(f"{PACKAGE}.modules."):
                forbid(path, line, name, "the entry points never reach into module subpackages")

    # -- rule 4's other half: what another module can reach through the surface is headless.
    surfaces = [
        *root.glob("modules/*/aspect.py"),
        *root.glob("modules/*/workflows.py"),
        *(path for package in headless for path in (root / "modules" / package).rglob("*.py")),
    ]
    for surface in sorted(surfaces):
        breaches = [
            (path, line, name)
            for path, line, name in reach(surface, root)
            if name.startswith((*QT_PACKAGES, f"{PACKAGE}.framework"))
        ]
        if breaches:
            path, line, name = breaches[0]
            more = f" (and {len(breaches) - 1} more)" if len(breaches) > 1 else ""
            violations.append(
                f"{surface.relative_to(root.parent)}: reaches {name!r} through "
                f"{path.relative_to(root.parent)}:{line}{more} — the surface another module "
                "imports is headless"
            )

    # -- rule 11 ------------------------------------------------------------------------------
    cycle = module_cycle(root)
    if cycle:
        violations.append("modules import each other in a cycle: " + " → ".join(cycle))

    return violations


def headless_packages(root: Path = SRC) -> set[str]:
    """The module packages with no ``module.py``: they register nothing, so the whole
    package is the surface another module may import (rule 4)."""
    return {
        package.name
        for package in (root / "modules").glob("*/")
        if (package / "__init__.py").is_file() and not (package / "module.py").is_file()
    }


def _file_of(name: str, root: Path) -> Path | None:
    """The source file a dotted name under ``root`` loads, or None outside the tree."""
    stem = root.parent.joinpath(*name.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def reach(start: Path, root: Path = SRC) -> list[tuple[Path, int, str]]:
    """Every import made by ``start`` and by everything under ``root`` it imports, followed
    to the end: (file, line, dotted-name) triples, nearest ``start`` first."""
    found: list[tuple[Path, int, str]] = []
    seen: set[Path] = set()
    pending = [start]
    while pending:
        path = pending.pop(0)
        if path in seen:
            continue
        seen.add(path)
        for line, name in imported_names(path, root):
            found.append((path, line, name))
            target = _file_of(name, root) if name.startswith(f"{PACKAGE}.") else None
            if target is not None:
                pending.append(target)
    return found


def module_cycle(root: Path = SRC) -> list[str]:
    """A cycle among the module packages, each edge named by its first import as
    ``a (file:line)``, ending where it began — or an empty list when there is none."""
    edges: dict[str, dict[str, str]] = {}
    for path in sorted(root.glob("modules/*/**/*.py")):
        own = module_dir_of(path, root)
        for line, name in imported_names(path, root):
            if own and name.startswith(f"{PACKAGE}.modules."):
                other = name.split(".")[2]
                if other != own:
                    where = f"{path.relative_to(root.parent)}:{line}"
                    edges.setdefault(own, {}).setdefault(other, where)

    trail: list[str] = []
    done: set[str] = set()

    def visit(package: str) -> list[str]:
        if package in trail:
            loop = [*trail[trail.index(package) :], package]
            return [*(f"{a} ({edges[a][b]})" for a, b in pairwise(loop)), package]
        if package in done:
            return []
        trail.append(package)
        for other in edges.get(package, {}):
            if cycle := visit(other):
                return cycle
        trail.pop()
        done.add(package)
        return []

    for package in sorted(edges):
        if cycle := visit(package):
            return cycle
    return []


def direct_commands(root: Path = SRC) -> int:
    """How many times a command built from ``domain/commands.py`` is pushed onto the undo
    stack (``….undo.push(…)``) or applied by a CLI verb (``context.apply(…)``) in place,
    outside a ``workflows.py``. A command bound to a name first is not counted: the count
    is a trend for a reviewer to watch, not a proof."""
    commands = ast.parse((root / "domain" / "commands.py").read_text())
    built_in = {
        node.name
        for node in commands.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and not node.name.startswith("_")
    }

    def last_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Attribute):
            return node.attr
        return node.id if isinstance(node, ast.Name) else None

    count = 0
    for path in root.rglob("*.py"):
        if path.name == "workflows.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            receiver = last_name(node.func.value)
            pushed = node.func.attr == "push" and receiver in ("undo", "_undo")
            applied = node.func.attr == "apply" and receiver == "context"
            if (pushed or applied) and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Call) and last_name(argument.func) in built_in:
                    count += 1
    return count


def declared_module_ids(root: Path = SRC) -> set[str]:
    """Every ``MODULE_ID = "…"`` (or ``_MODULE_ID``) at the top of a file under ``root``."""
    ids: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.parse(path.read_text(), filename=str(path)).body:
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
                if isinstance(node, ast.AnnAssign)
                else []
            )
            named = any(
                isinstance(t, ast.Name) and t.id in ("MODULE_ID", "_MODULE_ID") for t in targets
            )
            value = getattr(node, "value", None)
            if named and isinstance(value, ast.Constant) and isinstance(value.value, str):
                ids.add(value.value)
    return ids


# Rule 15: the base classes that make a class a tab, a modal or a scene, and the file stem
# that must say so. A subclass of a subclass counts — StatusBoard's two tabs are tabs.
ROLE_BASES = {
    "activity": ("ActivityBase", "EntityActivity"),
    "dialog": ("DialogFrame", "QDialog"),
    "scene": ("QGraphicsScene",),
}
ROLE_WORDS = {"activity": "tab", "dialog": "modal", "scene": "scene"}


def role_breaches(root: Path = SRC) -> list[str]:
    """Every module-package class held in a file whose name does not say its role (rule 15)."""
    files = sorted((root / "modules").rglob("*.py"))
    breaches = [
        f"{path.relative_to(root)}: view.py is retired — name the file for what it holds"
        for path in files
        if path.stem == "view" or path.stem.endswith("_view")
    ]
    classes = [
        (path, node)
        for path in files
        for node in ast.parse(path.read_text(), filename=str(path)).body
        if isinstance(node, ast.ClassDef)
    ]
    role_of = {base: role for role, bases in ROLE_BASES.items() for base in bases}
    grew = True
    while grew:  # Subclasses of subclasses, across files, until nothing new is learnt.
        grew = False
        for _path, node in classes:
            if node.name in role_of:
                continue
            for base in node.bases:
                name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
                if name in role_of:
                    role_of[node.name] = role_of[name]
                    grew = True
                    break
    for path, node in classes:
        role = role_of.get(node.name)
        if role is not None and path.stem != role and not path.stem.endswith(f"_{role}"):
            breaches.append(
                f"{path.relative_to(root)}: {node.name} is a {ROLE_WORDS[role]}, so its file is "
                f"{role}.py or <x>_{role}.py"
            )
    return breaches


def test_layering_rules_hold() -> None:
    violations = collect_violations()
    assert not violations, "architecture violations:\n" + "\n".join(violations)


def test_a_file_name_says_what_it_holds() -> None:
    breaches = role_breaches()
    assert not breaches, "file roles (rule 15):\n" + "\n".join(breaches)


def test_the_module_tests_mirror_the_packages() -> None:
    """``tests/modules/<package>/`` holds the tests of ``modules/<package>/``, so a folder there
    names a package; a test of the composition root, or of several packages at once, sits at
    ``tests/modules/`` itself, beside the root it tests."""
    tests = Path(__file__).parent / "modules"
    folders = {path.name for path in tests.iterdir() if path.is_dir() and path.name[0] != "_"}
    packages = {path.parent.name for path in (SRC / "modules").glob("*/__init__.py")}
    assert folders <= packages, f"test folders naming no package: {sorted(folders - packages)}"


def test_the_role_rule_sees_a_tab_a_modal_and_a_view(tmp_path) -> None:
    """Self-check for rule 15 over a throwaway tree: a tab two subclasses deep in module.py,
    a modal in a plain file and a ``view.py`` are each named."""
    package = tmp_path / PACKAGE / "modules" / "probe"
    package.mkdir(parents=True)
    (package / "module.py").write_text(
        "class Board(EntityActivity): ...\nclass OneBoard(Board): ...\n"
    )
    (package / "about.py").write_text("class AboutDialog(DialogFrame): ...\n")
    (package / "view.py").write_text("")
    (package / "activity.py").write_text("class Fine(Board): ...\n")
    breaches = "\n".join(role_breaches(tmp_path / PACKAGE))
    assert "Board is a tab" in breaches and "OneBoard is a tab" in breaches
    assert "AboutDialog is a modal" in breaches and "view.py is retired" in breaches
    assert "Fine" not in breaches


def test_every_headless_file_exists() -> None:
    """A rename that leaves an entry behind would drop that file out of the rule unseen."""
    missing = [
        f"{package}/{inside}"
        for package, files in HEADLESS_FILES.items()
        for inside in files
        if not (SRC / "modules" / package / inside).is_file()
    ]
    assert not missing, f"HEADLESS_FILES names files that do not exist: {missing}"


def test_the_rules_can_see_real_imports() -> None:
    """Self-check: the scanner finds imports at all.

    Without this, a refactor that broke the parser would turn the whole file into a silent
    no-op that passes forever — the worst possible failure mode for a constraint test.
    """
    names = [name for _line, name in imported_names(SRC / "app.py")]
    assert f"{PACKAGE}.modules" in names


def test_the_rules_can_catch_a_violation(tmp_path) -> None:
    """Self-check: a known-bad import is actually reported.

    Over a throwaway tree, never the real one. Writing the offender into ``src/`` and
    removing it in a ``finally`` was fine until the suite went parallel — after that it was a
    file appearing under another worker's feet while :func:`test_layering_rules_hold` walked
    ``src/``, failing perhaps one run in six and naming a file nobody could find afterwards,
    because the cleanup had already run. A test that mutates what another test reads is
    wrong however carefully it tidies up; the scanner takes a root so this one need not.
    """
    root = tmp_path / PACKAGE
    (root / "core").mkdir(parents=True)
    (root / "core" / "_architecture_probe.py").write_text(
        f"from {PACKAGE}.framework.tabs import TabHost\n"
    )
    violations = collect_violations(root)
    assert any("_architecture_probe" in violation for violation in violations)


def test_the_planning_tier_is_fenced_both_ways(tmp_path) -> None:
    """Self-check for rule 10: the graph never reads the planning model, and the planning
    model never reads a feature."""
    root = tmp_path / PACKAGE
    for package in ("domain", "planning", "modules"):
        (root / package).mkdir(parents=True)
        (root / package / "__init__.py").write_text("")
    # Every spelling of the same import: dotted, a package's name, and relative.
    probes = {
        root / "domain" / "_dotted.py": f"from {PACKAGE}.planning.status import Status\n",
        root / "domain" / "_named.py": f"from {PACKAGE} import planning\n",
        root / "domain" / "_relative.py": "from .. import planning\n",
        root / "planning" / "_dotted.py": f"from {PACKAGE}.modules.github import aspect\n",
        root / "planning" / "_named.py": f"from {PACKAGE} import modules\n",
        root / "planning" / "_relative.py": "from .. import modules\n",
    }
    for probe, source in probes.items():
        probe.write_text(source)
    violations = collect_violations(root)
    for probe in probes:
        named = str(probe.relative_to(tmp_path))
        assert any(violation.startswith(named) for violation in violations), named


def test_the_cross_module_surface_is_two_headless_files_per_package(tmp_path) -> None:
    """Self-check for rule 4: the surface is judged per package and by what it reaches."""
    root = tmp_path / PACKAGE
    for package in ("modules/a", "modules/b", "modules/b/sub", "domain"):
        (root / package).mkdir(parents=True)
        (root / package / "__init__.py").write_text("")
    probes = {
        root / "modules/a/_view.py": f"from {PACKAGE}.modules.b.view import Panel\n",
        root / "modules/a/_nested.py": f"from {PACKAGE}.modules.b.sub import aspect\n",
        root / "modules/a/workflows.py": f"from {PACKAGE}.domain.store import Store\n",
        # Reaches Qt only through a sibling it imports, which no filename rule would see.
        root / "modules/b/aspect.py": "from .widgets import Card\n",
    }
    allowed = {
        root / "modules/a/_facts.py": f"from {PACKAGE}.modules.b.aspect import read\n",
        root / "modules/a/_verb.py": f"from {PACKAGE}.modules.b import workflows\n",
    }
    for probe, source in {**probes, **allowed}.items():
        probe.write_text(source)
    (root / "modules/b/widgets.py").write_text("from PySide6.QtWidgets import QWidget\n")
    (root / "modules/b/module.py").write_text("")
    (root / "modules/a/module.py").write_text("")
    (root / "modules/b/view.py").write_text("")
    (root / "modules/b/sub/aspect.py").write_text("")
    (root / "modules/b/workflows.py").write_text("")
    (root / "domain/store.py").write_text("")
    violations = collect_violations(root)
    for probe in probes:
        named = str(probe.relative_to(tmp_path))
        assert any(violation.startswith(named) for violation in violations), named
    for probe in allowed:
        named = str(probe.relative_to(tmp_path))
        assert not any(violation.startswith(named) for violation in violations), named


def test_a_package_with_no_module_py_is_surface_all_through(tmp_path) -> None:
    """Self-check for rule 4's exception: every file of a package that registers nothing may
    be imported, and every one of them is held headless."""
    root = tmp_path / PACKAGE
    for package in ("modules/a", "modules/brief"):
        (root / package).mkdir(parents=True)
        (root / package / "__init__.py").write_text("")
    (root / "modules/a/module.py").write_text("")
    (root / "modules/a/_run.py").write_text(f"from {PACKAGE}.modules.brief.compose import x\n")
    (root / "modules/brief/compose.py").write_text("from .pane import y\n")
    (root / "modules/brief/pane.py").write_text("from PySide6.QtWidgets import QWidget\n")
    violations = collect_violations(root)
    assert not any(violation.startswith(f"{PACKAGE}/modules/a/") for violation in violations)
    assert any(
        violation.startswith(f"{PACKAGE}/modules/brief/compose.py: reaches 'PySide6")
        for violation in violations
    ), violations
    (root / "modules/brief/module.py").write_text("")
    violations = collect_violations(root)
    assert any(violation.startswith(f"{PACKAGE}/modules/a/_run.py") for violation in violations)


def test_a_module_cycle_is_named_edge_by_edge(tmp_path) -> None:
    """Self-check for rule 11."""
    root = tmp_path / PACKAGE
    for package in ("a", "b"):
        (root / "modules" / package).mkdir(parents=True)
    (root / "modules/a/aspect.py").write_text(f"from {PACKAGE}.modules.b.aspect import x\n")
    (root / "modules/b/aspect.py").write_text(f"\nfrom {PACKAGE}.modules.a.aspect import y\n")
    assert module_cycle(root) == [
        f"a ({PACKAGE}/modules/a/aspect.py:1)",
        f"b ({PACKAGE}/modules/b/aspect.py:2)",
        "a",
    ]


def test_the_root_does_not_grow() -> None:
    """Rule 12: the composition root is wiring, and its clusters are moving out. When it
    shrinks, lower ``ROOT_LINES`` to the new count."""
    lines = len((SRC / "modules" / "__init__.py").read_text().splitlines())
    assert lines <= ROOT_LINES, (
        f"modules/__init__.py has {lines} lines, over its ceiling of {ROOT_LINES}: "
        "the logic belongs in the module or the planning tier it serves"
    )


def test_built_in_commands_are_not_pushed_directly_more_than_today() -> None:
    """Rule 12: a verb that builds its own command in place is one a second surface will
    copy. When the count falls, lower ``DIRECT_COMMANDS`` to it."""
    count = direct_commands()
    assert count <= DIRECT_COMMANDS, (
        f"{count} built-in commands are pushed or applied directly outside a workflows.py, "
        f"over the ceiling of {DIRECT_COMMANDS}: build the change in the owning module's "
        "workflows.py and push what it returns"
    )


def test_the_direct_command_count_sees_a_push_and_an_apply(tmp_path) -> None:
    """Self-check for rule 12's counter."""
    root = tmp_path / PACKAGE
    (root / "domain").mkdir(parents=True)
    (root / "modules/a").mkdir(parents=True)
    (root / "domain/commands.py").write_text("class SetFieldCommand: ...\n")
    pushes = (
        "self._deps.undo.push(SetFieldCommand())\n"
        "context.apply(commands.SetFieldCommand())\n"
        "undo.push(change.command)\n"
    )
    (root / "modules/a/module.py").write_text(pushes)
    (root / "modules/a/workflows.py").write_text(pushes)
    assert direct_commands(root) == 2


def test_stored_module_ids_never_change() -> None:
    """Rule 13: a package may move or be renamed, but the id it stores data under is
    written into every plan and settings file, and changing it orphans them."""
    from dplanner.modules import default_module_formats

    found = declared_module_ids() | {f.module_id for f in default_module_formats()}
    removed = sorted(STORED_IDS - found)
    added = sorted(found - STORED_IDS)
    assert not removed, f"stored ids no longer declared: {removed} — a stored id never changes"
    assert not added, f"new stored ids: {added} — add them to STORED_IDS"


def test_a_retired_module_id_is_never_declared_again() -> None:
    """Rule 13's other half: a retired id's files may still sit in plans on disk, so a module
    declaring it again would adopt data it never wrote."""
    from dplanner.modules import default_module_formats

    found = declared_module_ids() | {f.module_id for f in default_module_formats()}
    assert not RETIRED_IDS & STORED_IDS, "an id is either stored or retired, never both"
    reused = sorted(RETIRED_IDS & found)
    assert not reused, f"retired ids declared again: {reused} — pick a new id"


def test_planning_admits_only_the_listed_aspects() -> None:
    """Rule 14: what planning/ interprets grows only by an edit to PLANNING_ASPECTS — read
    off the ``AspectSpec``s its files declare, since a file may declare two (the cut and
    the landing) under names of its own."""
    from importlib import import_module

    from dplanner.domain.aspects import AspectSpec

    admitted = {
        value.data_format.module_id
        for path in (SRC / "planning").glob("[!_]*.py")
        for value in vars(import_module(f"{PACKAGE}.planning.{path.stem}")).values()
        if isinstance(value, AspectSpec)
    }
    assert admitted == PLANNING_ASPECTS, (
        f"planning/ declares {sorted(admitted - PLANNING_ASPECTS)} unlisted and "
        f"{sorted(PLANNING_ASPECTS - admitted)} missing — admitting an aspect is a decision"
    )


def test_the_id_scanner_reads_a_declaration(tmp_path) -> None:
    """Self-check for rule 13's scanner."""
    root = tmp_path / PACKAGE
    root.mkdir()
    (root / "a.py").write_text('MODULE_ID = "a"\n_MODULE_ID: str = "b"\nOTHER_ID = "c"\n')
    assert declared_module_ids(root) == {"a", "b"}


def test_the_composition_root_imports_without_qt() -> None:
    """The CLI reaches a module's headless half through ``dplanner.modules``.

    If any module package re-exported its Qt class, or the composition root imported the
    modules at file scope, that import would pull in PySide6 — which costs most of a second
    and, on a machine with no GUI libraries, raises before the CLI has parsed a single
    argument. This asserts the property directly rather than trusting the convention.
    """
    probe = "import sys, dplanner.modules; assert 'PySide6' not in sys.modules, sorted(sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_the_cli_never_loads_qt() -> None:
    """The property the layering rules exist to protect, asserted directly.

    Importing the CLI and building its whole parser tree must not pull in PySide6. Without
    this, a stray import in any module's cli.py would put most of a second — and a hard
    dependency on graphics libraries — into every invocation, and nothing would notice.
    """
    probe = (
        "import sys;"
        "from dplanner.cli.command import CliRegistry;"
        "from dplanner.cli.main import build_tree;"
        "from dplanner.modules import aspect_specs, default_cli_commands, default_module_formats;"
        "r = CliRegistry(); r.register_all(default_cli_commands()); build_tree(r);"
        # entry.py also calls default_module_formats() at CLI time (aspect_specs() feeds
        # it and the skill); without them here, a Qt import reached only through those
        # paths would go unnoticed — the composition root is exempt from the static rules.
        "default_module_formats(); aspect_specs();"
        "assert 'PySide6' not in sys.modules, sorted(m for m in sys.modules if 'Side' in m)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_the_theme_package_imports_without_qt() -> None:
    """A theme provider is Qt-free by contract, and what it reads is the theme package.

    The themes, the providers and the Omarchy mapping — and the two provider modules over
    them — must therefore import without PySide6: the Qt half of the package is imported
    inside ``apply_theme``, the one function that needs it, and this asserts that it stayed
    there rather than trusting the layout.

    ``palettes`` is here for a second reason: the milestone colour maps are read by a
    module's Qt-free half (``schedule``' ``assumptions.py``, ``cli.py`` and
    ``report.py``), so one ``QColor`` in that file would put a graphics stack in every
    ``dplanner`` invocation. ``glyph_source`` is here for the same one: the report draws a
    card's glyph from it, and the report is built by the CLI. ``theme/tones.py`` is
    deliberately *not* in this probe — it holds ``QColor`` constants and only the window
    reads it.
    """
    probe = (
        "import sys;"
        "import dplanner.theme, dplanner.theme.providers, dplanner.theme.omarchy;"
        "import dplanner.theme.palettes, dplanner.theme.glyph_source;"
        "from dplanner.modules.theme_omarchy import themes;"
        "from dplanner.modules.theme_system import themes;"
        "assert 'PySide6' not in sys.modules, sorted(m for m in sys.modules if 'Side' in m)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
