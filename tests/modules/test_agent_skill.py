"""The Tools action that previews, installs and removes the skill the CLI writes."""

import pytest

from dplanner.cli.command import CliRegistry
from dplanner.cli.skill import REFERENCE_FILE, SKILL_FILE, generate
from dplanner.modules.agent_skill.dialog import AgentSkillDialog


@pytest.fixture
def skill_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path / ".claude" / "skills" / "dplanner"


def composition_root_files() -> dict[str, str]:
    from dplanner.modules import aspect_specs, default_cli_commands

    registry = CliRegistry()
    registry.register_all(default_cli_commands())
    return generate(registry, aspect_specs())


def test_the_action_opens_the_dialog(services, skill_home, monkeypatch):
    opened = []
    monkeypatch.setattr(AgentSkillDialog, "exec", lambda self: opened.append(self))

    services.actions.run("agent_skill.manage", services.context.current())

    (dialog,) = opened
    assert dialog._directory == skill_home
    contents = [dialog.tabs.widget(i).toPlainText() for i in range(dialog.tabs.count())]
    files = composition_root_files()
    assert contents == [files[SKILL_FILE], files[REFERENCE_FILE]]
    assert not (skill_home / SKILL_FILE).exists()  # previewing writes nothing


def test_installing_from_the_dialog_writes_what_the_cli_writes(services, skill_home):
    """One generator, not two: a second implementation would drift within a month."""
    files = composition_root_files()
    dialog = AgentSkillDialog(files, skill_home, None)
    assert dialog.primary.text() == "Install"
    assert not dialog.remove_button.isEnabled()

    dialog.primary.click()

    assert (skill_home / SKILL_FILE).read_text() == files[SKILL_FILE]
    assert (skill_home / REFERENCE_FILE).read_text() == files[REFERENCE_FILE]
    assert not dialog.primary.isEnabled()
    assert dialog.remove_button.isEnabled()


def test_a_hand_edited_skill_reads_as_stale(services, skill_home):
    files = composition_root_files()
    installer = AgentSkillDialog(files, skill_home, None)
    installer.primary.click()
    (skill_home / SKILL_FILE).write_text("edited by hand\n")

    dialog = AgentSkillDialog(files, skill_home, None)
    assert dialog.primary.text() == "Update"
    assert dialog.primary.isEnabled()

    dialog.primary.click()
    assert (skill_home / SKILL_FILE).read_text() == files[SKILL_FILE]


def test_remove_deletes_the_skill(services, skill_home):
    files = composition_root_files()
    dialog = AgentSkillDialog(files, skill_home, None)
    dialog.primary.click()

    dialog.remove_button.click()

    assert not skill_home.exists()
    assert dialog.primary.text() == "Install"
    assert dialog.primary.isEnabled()
    assert not dialog.remove_button.isEnabled()
