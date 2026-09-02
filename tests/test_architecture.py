"""Layering rules, enforced.

The architecture is ``core`` → ``domain`` → ``framework`` → ``modules`` → the composition
root (``modules/__init__.py``) → ``app``. These tests parse every source file's imports with
the standard library's ``ast`` — no Qt is loaded, no import is executed — and fail with the
offending file and line when a rule is broken.

``TYPE_CHECKING``-only imports count on purpose: type coupling is still coupling, and an
architecture that holds only at runtime is one refactor from not holding at all.

The rules, in prose (see also CLAUDE.md):

1. ``core/`` imports no Qt and nothing from the rest of the application. It is the bottom
   layer, and it is what every application built from this template shares.
2. ``domain/`` imports no Qt, and imports ``core`` only. Your model must stay testable with
   plain pytest, and must never depend on the machinery that displays it.
3. ``framework/`` never imports ``modules`` or ``app``. It may use ``core``, ``domain`` and
   ``theme``.
4. Modules never import each other. Only ``modules/__init__.py`` may import them all.
5. Modules never import ``AppServices``, the builder, or the concrete window — they receive
   typed ``Deps`` objects and reach the window through the capability protocols.
6. ``app.py`` and ``entry.py`` never reach into a module subpackage; they may import the
   composition root.
7. ``cli/`` imports no Qt and nothing above ``domain/``, and a module's ``cli.py`` and
   ``aspect.py`` are the same: importable without a graphics stack. The CLI is how an agent
   drives this application, and it has to start in milliseconds on a machine with no GUI
   libraries at all.
8. Only ``core/storage/`` and the composition root may import a *concrete* storage provider.
   Everything else depends on the protocols — which is what makes "swap the storage system"
   true rather than aspirational.

**When one of these fails, fix the dependency direction, not the test.** Every rule has a
supported way to get what the shortcut wanted: a capability protocol, a typed callback on
your ``Deps``, or a registry.
"""

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "dplanner"
PACKAGE = SRC.name

QT_PACKAGES = ("PySide6", "shiboken6")

# Files inside a module package that the CLI reaches, and which must therefore load no Qt.
# Checked by name because that is what makes the rule visible from the filename: if the
# composition root imports a file at CLI time, it belongs in this tuple.
HEADLESS_FILES = (
    "cli.py",
    "aspect.py",
    "clipboard.py",
    "positions.py",
    "placement.py",
    "named_layouts.py",
    "sorts.py",
    "regions.py",
    "marks.py",
    "schedule.py",
    "collect.py",
    "runs.py",
    "terminal.py",
    "documents.py",
    "handoff.py",
    "prompt.py",
    "membership.py",
    "gh.py",
    "pdf.py",
)
CONCRETE_STORAGE = (
    f"{PACKAGE}.core.storage.local",
    f"{PACKAGE}.core.storage.git",
    f"{PACKAGE}.core.storage.github",
    f"{PACKAGE}.core.storage.locations",
)


def imported_names(path: Path, root: Path = SRC) -> list[tuple[int, str]]:
    """Absolute names imported by ``path``: (line, dotted-name) pairs.

    Relative imports are resolved against the file's own package, so ``from . import x``
    inside ``dplanner/modules/projects/`` reads as ``dplanner.modules.projects``.
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
    return names


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
                        f"{PACKAGE}.framework",
                        f"{PACKAGE}.modules",
                        f"{PACKAGE}.theme",
                        f"{PACKAGE}.app",
                    )
                ):
                    forbid(path, line, name, "domain/ may import core/ only")
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
                    forbid(path, line, name, "cli/ sits above domain/ and below the modules")
            elif top == "framework":
                if name.startswith(f"{PACKAGE}.modules") or name == f"{PACKAGE}.app":
                    forbid(path, line, name, "framework/ never imports modules or the app")
            elif top == "modules":
                if is_composition_root:
                    continue  # The one place allowed to import everything.
                own = module_dir_of(path, root)
                # The headless half of a module. The composition root reaches these through
                # `dplanner.modules`, so one Qt import here would put a graphics stack in
                # every CLI invocation.
                if path.name in HEADLESS_FILES:
                    if name.startswith(QT_PACKAGES):
                        forbid(path, line, name, f"a module's {path.name} loads no Qt")
                    if name.startswith(f"{PACKAGE}.framework"):
                        forbid(path, line, name, f"a module's {path.name} uses core and domain")
                if name.startswith(f"{PACKAGE}.modules."):
                    other = name.split(".")[2] if len(name.split(".")) > 2 else ""
                    if other and other != own:
                        forbid(path, line, name, "modules never import each other")
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

    return violations


def test_layering_rules_hold() -> None:
    violations = collect_violations()
    assert not violations, "architecture violations:\n" + "\n".join(violations)


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
