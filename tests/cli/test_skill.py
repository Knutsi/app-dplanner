"""The generated skill: a projection of the registry, and the same bytes every time."""

import os
import subprocess
import sys
from io import StringIO

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.main import run
from dplanner.cli.skill import REFERENCE_FILE, SKILL_FILE, generate, install, status, target_dir
from dplanner.modules import aspect_specs, default_cli_commands, default_module_formats


@pytest.fixture
def registry():
    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    return registry


@pytest.fixture
def files(registry):
    return generate(registry, aspect_specs())


def test_every_command_appears_exactly_once(registry, files):
    """The point of generating it: the skill cannot describe a command that does not exist,
    and cannot omit one that does."""
    skill = files[SKILL_FILE]
    for command in registry.commands():
        # The index bullet specifically: the prose above it may mention a command too.
        assert skill.count(f"- `dplanner {command.id}` — ") == 1


def test_every_command_has_its_arguments_in_the_reference(registry, files):
    reference = files[REFERENCE_FILE]
    for command in registry.commands():
        assert f"## `dplanner {command.id}`" in reference
        assert f"usage: dplanner {command.id}" in reference


def test_every_aspect_is_described(files):
    for spec in aspect_specs():
        assert spec.summary in files[SKILL_FILE]


def test_the_edge_vocabulary_is_described(files):
    assert "cycles are refused" in files[SKILL_FILE]


def test_the_skill_has_frontmatter_a_skill_loader_can_read(files):
    head = files[SKILL_FILE].splitlines()
    assert head[0] == "---"
    assert head[1] == "name: dplanner"
    assert head[2].startswith("description: ")


def test_the_output_does_not_depend_on_the_terminal_it_was_generated_in():
    """Argparse wraps to the terminal width by default, so the same command in two windows
    would write two different files — and this one goes into version control."""
    probe = (
        "from dplanner.cli.command import CliRegistry;"
        "from dplanner.cli.skill import generate;"
        "from dplanner.modules import aspect_specs, default_cli_commands;"
        "r = CliRegistry(); r.register_all(default_cli_commands());"
        "print(repr(generate(r, aspect_specs())))"
    )
    outputs = []
    for columns in ("40", "200"):
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "COLUMNS": columns},
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


# -- installing --------------------------------------------------------------------------------


def invoke(registry, *argv):
    out, err = StringIO(), StringIO()
    code = run(registry, default_module_formats(), list(argv), out, err)
    assert code == 0, err.getvalue()
    return out.getvalue()


def test_the_skill_verbs_need_no_product(registry, tmp_path, monkeypatch):
    """An agent asks what DPlanner is before it has found a workspace."""
    monkeypatch.chdir(tmp_path)
    assert "name: dplanner" in invoke(registry, "skill", "show")


def test_installing_reports_stale_then_current(files, tmp_path):
    assert status(files, tmp_path) == "missing"
    install(files, tmp_path)
    assert status(files, tmp_path) == "installed"
    (tmp_path / SKILL_FILE).write_text("edited by hand\n")
    assert status(files, tmp_path) == "stale"


def test_project_install_travels_with_the_repository(registry, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(registry, "skill", "install", "--project")
    assert (tmp_path / ".claude" / "skills" / "dplanner" / SKILL_FILE).is_file()


def test_user_install_goes_to_the_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert target_dir(user=True) == tmp_path / ".claude" / "skills" / "dplanner"
