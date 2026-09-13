"""The generated skill: a projection of the registry, and the same bytes every time."""

import os
import subprocess
import sys
from io import StringIO

import pytest
from tests.cli.skill_helpers import noun_verbs

from dplanner.cli.install import install_command, path_hint, worktree_warning
from dplanner.cli.main import WINDOW_SHORTCUT, WINDOW_WORD, run
from dplanner.cli.skill import (
    REFERENCE_FILE,
    SKILL_FILE,
    generate,
    install,
    status,
    target_dir,
    uninstall,
)
from dplanner.modules import aspect_specs, default_module_formats


@pytest.fixture
def files(registry):
    return generate(registry, aspect_specs())


def test_every_noun_is_one_line_naming_its_verbs(registry, files):
    """The point of generating it: the skill cannot describe a command that does not exist,
    and cannot omit one it offers. A summary per verb was a third of the file and said what
    `--help` says, so the index names the verbs and nothing else."""
    verbs = noun_verbs(files[SKILL_FILE])
    for noun, commands in registry.groups().items():
        offered = {command.path[1] for command in commands if command.in_skill}
        if not offered:
            assert noun not in verbs  # A noun with nothing to offer is not a noun here.
            continue
        # A set, not a containment check: a verb printed twice is as wrong as one missing.
        assert {verb.removesuffix("†") for verb in verbs[noun]} == offered


def test_the_command_index_is_an_index(files):
    """The size rule this shape exists for — 19,793 chars of per-verb summaries before it.
    A regression here is somebody putting the prose back."""
    skill = files[SKILL_FILE]
    section = skill[skill.index("## Commands") : skill.index("## Aspects a step can carry")]
    assert len(section) < 4_000, len(section)


def test_every_offered_command_has_its_arguments_in_the_reference(registry, files):
    reference = files[REFERENCE_FILE]
    for command in registry.commands():
        if not command.in_skill:
            assert f"## `dplanner {command.id}`" not in reference
            continue
        assert f"## `dplanner {command.id}`" in reference
        assert f"usage: dplanner {command.id}" in reference


def test_a_verb_kept_out_of_the_skill_is_still_a_verb(registry, files):
    """`in_skill=False` is the CLI twin of `ActionSpec.in_menus`: registered and runnable,
    named by no generated file. The region verbs are what it exists for."""
    kept_out = [command.id for command in registry.commands() if not command.in_skill]
    assert kept_out == [
        "region add",
        "region delete",
        "region fit",
        "region list",
        "region rename",
    ]
    for name, text in files.items():
        assert "region" not in text.lower(), name


def test_every_aspect_is_described(files):
    for spec in aspect_specs():
        assert spec.summary in files[SKILL_FILE]


def test_the_edge_vocabulary_is_described(files):
    assert "cycles are refused" in files[SKILL_FILE]


def test_the_skill_teaches_the_spatial_loop_and_never_mentions_regions(files):
    """Look, sort, make room or tidy, look again, keep. A skill that does not offer regions
    need not forbid them either — the prohibition went with the verbs."""
    skill = " ".join(files[SKILL_FILE].split())
    assert "layout show <project> --map" in skill
    assert "layout shift <project> --x 640 --by 300" in skill
    assert "layout tidy <project>" in skill
    assert "region" not in skill.lower()


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


def test_the_skill_prices_an_agent_task_at_two_hours(files):
    skill = files[SKILL_FILE]
    assert "## Estimating agent work" in skill
    assert "2 hours per task" in skill
    assert "--days 0.25" in skill


def test_the_skill_asks_for_batched_agent_steps_unless_the_topology_says_otherwise(files):
    """What the first real project taught: a step is a launch and a review, so similar
    work belongs in one large step — and the topology is the one thing that overrides."""
    prose = " ".join(files[SKILL_FILE].split())
    assert "## Cutting agent steps" in files[SKILL_FILE]
    assert "unless the project's topology says otherwise" in prose
    assert "lump similar work into one large step" in prose


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
    assert "$DPLANNER_PROJECT" in skill
    assert "## Where the plan lives" in skill
    assert "project move <project> --into <plan repository>" in skill
    assert "when the developer asks, never unasked" in skill


def test_the_skill_has_frontmatter_a_skill_loader_can_read(files):
    head = files[SKILL_FILE].splitlines()
    assert head[0] == "---"
    assert head[1] == "name: dplanner"
    assert head[2].startswith("description: ")


def test_the_skill_says_how_to_discover_commands_and_never_names_the_window(files):
    """An agent that runs `dplanner` bare is looking for this list; the skill tells it where
    the list is, and never the one word that opens a window on the developer's desktop."""
    assert "`dplanner --help`" in files[SKILL_FILE]
    for content in files.values():
        assert f"dplanner {WINDOW_WORD}" not in content
        assert WINDOW_SHORTCUT not in content  # Nor the word typed for you.


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
    monkeypatch.setattr("dplanner.cli.install._which", lambda _name: "/usr/bin/dplanner")
    assert path_hint() is None


def test_path_hint_names_an_editable_install_from_a_checkout(monkeypatch):
    """A skill that tells agents to run a command they do not have is half an install."""
    import shlex

    monkeypatch.setattr("dplanner.cli.install._which", lambda _name: None)
    hint = path_hint()
    assert hint is not None
    assert hint.startswith("uv tool install --editable ")
    assert hint == shlex.join(install_command())


def test_status_verb_reports_whether_the_command_resolves(registry, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("dplanner.cli.install._which", lambda _name: None)
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
