"""The generated skill: a projection of the registry, and the same bytes every time."""

import os
import subprocess
import sys
from io import StringIO

import pytest

from dplanner.cli.main import run
from dplanner.cli.skill import (
    REFERENCE_FILE,
    SKILL_FILE,
    generate,
    install,
    install_command,
    path_hint,
    status,
    target_dir,
    uninstall,
    worktree_warning,
)
from dplanner.modules import aspect_specs, default_module_formats


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


def test_the_skill_teaches_description_as_the_briefing(files):
    """The de-confusion the preamble carries: one text per step, and the real flag name —
    `--project` parses as the scope option and then fails, so the skill must never say it."""
    skill = files[SKILL_FILE]
    assert "The description is the briefing" in skill
    assert "agent set --for-project" in skill
    assert "agent set --project" not in skill


def test_the_skill_teaches_two_part_descriptions(files):
    """The convention the first field run surfaced: a human part first, then a delimited
    agent section that names the figures — and the way back from a separate instruction."""
    skill = files[SKILL_FILE]
    assert "## Writing descriptions" in skill
    assert "## Approach" in skill
    assert "tasks to accomplish" in skill  # Outcomes, not a how-to sequence.
    assert "Name every attached figure" in skill
    assert "agent set <step> --clear" in skill


def test_the_skill_prices_an_agent_task_at_ninety_minutes(files):
    skill = files[SKILL_FILE]
    assert "## Estimating agent work" in skill
    assert "90 minutes per task" in skill
    assert "--days 0.25" in skill


def test_the_skill_states_the_argument_shape_and_idempotency_rules(files):
    """The two shape rules agents guessed wrong at: which noun is the positional, and
    that clearing what is already clear succeeds."""
    skill = files[SKILL_FILE]
    assert "The positional names the thing the verb acts on" in skill
    assert "Already clear is success" in skill


def test_the_skill_says_page_disambiguates_a_recurring_quote(files):
    prose = " ".join(files[SKILL_FILE].split())
    assert "when the same sentence appears on several pages" in prose


def test_the_skill_says_how_the_current_project_is_found(files):
    """The half a registry cannot render: the walk, the pointer file, and the library."""
    skill = files[SKILL_FILE]
    assert "## Where the project is" in skill
    assert "project.dproj" in skill and ".dplanner" in skill
    assert "--library PATH" in skill and "$DPLANNER_LIBRARY" in skill


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


def test_the_skill_verbs_need_no_library(registry, tmp_path, monkeypatch):
    """An agent asks what DPlanner is before it has found a library."""
    monkeypatch.chdir(tmp_path)
    assert "name: dplanner" in invoke(registry, "skill", "show")


def test_installing_reports_stale_then_current(files, tmp_path):
    assert status(files, tmp_path) == "missing"
    install(files, tmp_path)
    assert status(files, tmp_path) == "installed"
    (tmp_path / SKILL_FILE).write_text("edited by hand\n")
    assert status(files, tmp_path) == "stale"


def test_repo_install_travels_with_the_repository(registry, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(registry, "skill", "install", "--repo")
    assert (tmp_path / ".claude" / "skills" / "dplanner" / SKILL_FILE).is_file()


def test_user_install_goes_to_the_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert target_dir(user=True) == tmp_path / ".claude" / "skills" / "dplanner"


def test_path_hint_is_quiet_when_the_command_resolves(monkeypatch):
    monkeypatch.setattr("dplanner.cli.skill.shutil.which", lambda _name: "/usr/bin/dplanner")
    assert path_hint() is None


def test_path_hint_names_an_editable_install_from_a_checkout(monkeypatch):
    """A skill that tells agents to run a command they do not have is half an install."""
    import shlex

    monkeypatch.setattr("dplanner.cli.skill.shutil.which", lambda _name: None)
    hint = path_hint()
    assert hint is not None
    assert hint.startswith("uv tool install --editable ")
    assert hint == shlex.join(install_command())


def test_status_verb_reports_whether_the_command_resolves(registry, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("dplanner.cli.skill.shutil.which", lambda _name: None)
    out = invoke(registry, "skill", "status", "--repo")
    assert "not on PATH" in out


def test_a_worktree_checkout_warns_and_names_the_main_one(tmp_path):
    """An editable install into a worktree breaks when the worktree is removed."""
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n")

    warning = worktree_warning(worktree)
    assert warning is not None
    assert str(worktree) in warning
    assert f"uv tool install --editable {main}" in warning


def test_a_main_checkout_raises_no_worktree_warning(tmp_path):
    (tmp_path / ".git").mkdir()
    assert worktree_warning(tmp_path) is None
    assert worktree_warning(tmp_path / "no-git-at-all") is None


def test_uninstall_removes_only_what_install_wrote(files, tmp_path):
    directory = tmp_path / "skill"
    install(files, directory)
    (directory / "notes.md").write_text("mine\n")

    uninstall(files, directory)

    assert status(files, directory) == "missing"
    assert (directory / "notes.md").read_text() == "mine\n"

    plain = tmp_path / "plain"
    install(files, plain)
    uninstall(files, plain)
    assert not plain.exists()


def test_uninstall_verb(registry, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invoke(registry, "skill", "install", "--repo")
    invoke(registry, "skill", "uninstall", "--repo")
    assert not (tmp_path / ".claude" / "skills" / "dplanner").exists()
    assert "nothing installed" in invoke(registry, "skill", "uninstall", "--repo")
