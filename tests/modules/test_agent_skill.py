"""The Tools action that installs the same skill the CLI writes."""

import pytest

from dplanner.cli.skill import SKILL_FILE


@pytest.fixture
def skill_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / ".claude" / "skills" / "dplanner"


def test_the_label_says_what_pressing_it_would_do(services, skill_home):
    spec = services.actions.spec("agent_skill.install")
    assert spec.state(services.context.current()).label == "&Install Agent Skill…"

    services.actions.run("agent_skill.install", services.context.current())
    assert (skill_home / SKILL_FILE).is_file()
    assert spec.state(services.context.current()).label == "Agent Skill Is &Current"


def test_an_edited_skill_reads_as_out_of_date(services, skill_home):
    services.actions.run("agent_skill.install", services.context.current())
    (skill_home / SKILL_FILE).write_text("edited by hand\n")
    spec = services.actions.spec("agent_skill.install")
    assert spec.state(services.context.current()).label == "&Update Agent Skill…"


def test_the_window_writes_what_the_cli_writes(services, skill_home):
    """One generator, not two: a second implementation would drift within a month."""
    from dplanner.cli.command import CliRegistry
    from dplanner.cli.skill import generate
    from dplanner.modules import aspect_specs, default_cli_commands

    services.actions.run("agent_skill.install", services.context.current())
    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    assert (skill_home / SKILL_FILE).read_text() == generate(registry, aspect_specs())[SKILL_FILE]
